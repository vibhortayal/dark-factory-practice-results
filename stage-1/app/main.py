"""Entry point: listen on 0.0.0.0:$PORT (default 8080)."""
import os

from .server import Handler, Server


def main():
    port = int(os.environ.get("PORT", "8080"))
    print(f"pocketful listening on 0.0.0.0:{port}", flush=True)
    Server(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
