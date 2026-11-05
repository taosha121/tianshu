import threading
import time
import webbrowser

import uvicorn


def main():
    def _open():
        time.sleep(0.8)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run("tianshu.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
