"""실행 진입점. 프로그램 폴더에서  python run.py  → 브라우저가 자동으로 열린다."""
from __future__ import annotations

import argparse
import webbrowser

DEFAULT_PORT = 8765


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="학원 학생 관리 (이 PC 전용, 브라우저 화면)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"접속 포트 (기본 {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    args = parser.parse_args(argv)

    from .db.database import connect
    from .web.server import AppServer

    url = f"http://127.0.0.1:{args.port}/"
    conn = connect()
    try:
        server = AppServer(("127.0.0.1", args.port), conn)
    except OSError:
        conn.close()
        print(f"이미 실행 중이거나 포트 {args.port}을(를) 사용할 수 없습니다. 실행 중인 화면을 엽니다: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    print("학원 학생 관리 프로그램이 실행 중입니다.")
    print(f"브라우저 주소: {url}   (이 PC에서만 접속할 수 있습니다)")
    print("종료: 화면 우측 상단의 '프로그램 종료' 버튼 또는 이 창에서 Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        conn.close()
        print("프로그램을 종료했습니다.")


if __name__ == "__main__":
    main()
