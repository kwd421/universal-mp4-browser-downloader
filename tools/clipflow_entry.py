"""ClipFlow frozen-entry dispatcher.

Keep worker branches free of Qt imports so the frozen app can spawn lightweight
worker processes from the same executable.
"""

import sys


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--clipflow-download-worker":
        try:
            from tools.clipflow_download_process import main as worker_main
        except ImportError:
            from clipflow_download_process import main as worker_main
        return worker_main(argv)
    if argv and argv[0] == "--clipflow-analysis-worker":
        try:
            from tools.clipflow_analysis_process import main as worker_main
        except ImportError:
            from clipflow_analysis_process import main as worker_main
        return worker_main(argv)

    try:
        from tools.clipflow_qt import main as gui_main
    except ImportError:
        from clipflow_qt import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
