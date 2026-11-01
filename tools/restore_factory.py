"""Restore RC startup from a personal backup or the documented author fallback."""

import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import subprocess
import tempfile
import sys

if __package__:
    from .save_autostart import ROOT, read_files, remote
else:
    from save_autostart import ROOT, read_files, remote

STARTUP_FILES = ('boot.py', 'main.py')


def is_factory_rc_boot(boot):
    """Recognize the two public RC entry styles without executing the backup."""
    try:
        tree = ast.parse(boot.decode('utf-8-sig'))
    except (SyntaxError, UnicodeError, ValueError):
        return False
    is_rc = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == '_PRODUCT_NAME'
                for target in node.targets)
        and isinstance(node.value, ast.Constant) and node.value.value == 'RC'
        for node in tree.body)
    calls_main = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'rc_main'
        and node.func.attr == 'main' for node in ast.walk(tree))
    legacy_entry = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == 'open' and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in ('./app/rc_main.py', '/app/rc_main.py', 'app/rc_main.py')
        for node in ast.walk(tree))
    return is_rc and (calls_main or legacy_entry)


def load_backup(directory):
    directory = Path(directory).resolve()
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if not isinstance(manifest, dict):
        raise ValueError('manifest.json must contain a backup record object.')
    files = manifest.get('files')
    if not isinstance(files, dict) or not all(name in files for name in STARTUP_FILES):
        raise ValueError('Backup must record both boot.py and main.py in manifest.json.')
    expected = {}
    for name in STARTUP_FILES:
        value = files[name]
        if value is None:
            expected[name] = None
            if (directory / name).exists():
                raise ValueError('Backup file disagrees with absence recorded in manifest: ' + name)
        elif isinstance(value, str):
            content = bytes.fromhex(value)
            compile(content, name, 'exec')
            local = directory / name
            if local.exists() and local.read_bytes() != content:
                raise ValueError('Backup file disagrees with manifest: ' + name)
            expected[name] = content.hex()
        else:
            raise ValueError('Invalid backup contents: ' + name)
    if expected['boot.py'] is None or not is_factory_rc_boot(bytes.fromhex(expected['boot.py'])):
        raise ValueError('This backup does not contain a recognized factory RC boot.py.')
    return manifest, expected


def factory_backups(root):
    candidates = []
    for manifest_path in sorted(Path(root).glob('*/manifest.json')):
        try:
            manifest, _ = load_backup(manifest_path.parent)
            candidates.append((manifest_path.parent, manifest))
        except (OSError, ValueError, SyntaxError, TypeError):
            continue
    return candidates


def show_backups(candidates):
    if not candidates:
        print('没有找到原厂 RC 启动备份。请按 README 找回个人备份或作者备用备份。')
    for index, (directory, manifest) in enumerate(candidates, 1):
        label = ' [作者备用 RC 01.00.00.21]' if directory.name == '20261018-122213-109661' else ''
        print('%d. %s%s  [备份时串口: %s]' %
              (index, directory.name, label, manifest.get('port', '未记录')))
    if candidates:
        print('优先选择自己的原厂备份；作者备用备份的适用条件见 README。串口号不能证明板卡身份。')


def restore(port, directory, backup_root=None):
    directory = Path(directory).resolve()
    _, expected = load_backup(directory)  # Validate locally before touching USB.
    preflight = (
        "import os\n"
        "assert 'app' in os.listdir('/'), 'Factory app directory is missing'\n"
        "assert 'bbl' in os.listdir('/'), 'Factory bbl directory is missing'\n"
        "assert any(name in os.listdir('/app') for name in ('rc_main.py', 'rc_main.mpy')), 'Factory RC entry is missing'\n"
    )
    remote(port, 'exec', preflight)
    current = read_files(port, ('boot.py', 'main.py', 'rc_config'))
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_root = Path(backup_root) if backup_root is not None else ROOT / 'backups'
    safety = backup_root / ('before_rc_restore_' + stamp)
    safety.mkdir(parents=True)
    record = {'port': port, 'restore_from': str(directory), 'files': current}
    (safety / 'manifest.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    for name, content in current.items():
        if content is not None:
            saved = safety / name
            saved.write_bytes(bytes.fromhex(content))
            if saved.read_bytes().hex() != content:
                raise RuntimeError('Current-file backup verification failed: ' + name)
    print('恢复前的当前文件已备份到: ' + str(safety), flush=True)

    staged = {}
    with tempfile.TemporaryDirectory(prefix='cyberbrick-rc-restore-') as temp:
        for name, content in expected.items():
            if content is None:
                continue
            staged_name = name + '.restore_' + stamp
            staged[staged_name] = content
            local = Path(temp) / name
            local.write_bytes(bytes.fromhex(content))
            remote(port, 'fs', 'cp', str(local), ':/' + staged_name)
    if read_files(port, tuple(staged)) != staged:
        raise RuntimeError('Staged verification failed; startup entries were not changed. Backup: ' + str(safety))

    retained_main = 'main.py.before_rc_restore_' + stamp
    commands = ['import os']
    if current['main.py'] is not None:
        commands.append('os.rename(%r, %r)' % ('/main.py', '/' + retained_main))
    if expected['main.py'] is not None:
        commands.append('os.rename(%r, %r)' % ('/main.py.restore_' + stamp, '/main.py'))
    # Switch the boot entry only after the intended main.py state is in place.
    commands.append('os.rename(%r, %r)' % ('/boot.py.restore_' + stamp, '/boot.py'))
    commands.append('os.sync()')
    remote(port, 'exec', '\n'.join(commands) + '\n')
    actual = read_files(port, ('boot.py', 'main.py', 'rc_config'))
    if actual != dict(expected, rc_config=current['rc_config']):
        raise RuntimeError('Restored startup read-back verification failed. Backup: ' + str(safety))
    if current['main.py'] is not None:
        if read_files(port, (retained_main,))[retained_main] != current['main.py']:
            raise RuntimeError('Retained application verification failed. Backup: ' + str(safety))
    print('Restored and verified: factory RC startup.')
    print('原厂启动文件已读回校验。现有配置及配对信息保留。')
    print('请按 RST 或重新供电，再打开 CyberBrick 软件连接。')
    return safety


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Current board USB port, for example COM5.')
    parser.add_argument('--backup', type=Path, help='Factory backup directory; see README for the author fallback.')
    parser.add_argument('--list-backups', action='store_true', help='List local backups; do not connect to USB.')
    args = parser.parse_args()
    if args.list_backups:
        show_backups(factory_backups(ROOT / 'backups'))
        return
    if not args.port:
        parser.error('--port is required when restoring.')
    directory = args.backup
    if directory is None:
        candidates = factory_backups(ROOT / 'backups')
        show_backups(candidates)
        if not candidates:
            raise ValueError('No factory backup available. No board files were changed.')
        answer = input('请输入属于当前板卡的原厂备份编号；直接回车取消: ').strip()
        if not answer:
            print('已取消，没有连接板卡。')
            return
        if not answer.isdigit() or not 1 <= int(answer) <= len(candidates):
            raise ValueError('Invalid backup selection. No board files were changed.')
        directory = candidates[int(answer) - 1][0]
    elif not directory.is_absolute():
        directory = ROOT / directory
    restore(args.port, directory)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, SyntaxError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('恢复未完成: ' + str(error), file=sys.stderr)
        print('请保留显示的备份路径及完整报错，关闭其他串口程序后排查。', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n操作中断。若已经开始写入，请保留备份并重新检查恢复结果。', file=sys.stderr)
        sys.exit(130)
