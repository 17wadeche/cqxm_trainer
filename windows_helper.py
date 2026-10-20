import sys
def main():
    if sys.argv[1:] == ['--install']:
        from install_native import main as install
        install()
        return 0
    if sys.argv[1:] == ['--self-test']:
        from packaging_smoke import main as smoke
        return smoke()
    from native_host import main as native
    return native()
if __name__ == '__main__':
    raise SystemExit(main())
