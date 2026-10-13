"""Publication Cardmarket lancée depuis l'interface : tâche de fond avec progression consultable.

Une seule publication à la fois. Elle utilise sa propre connexion SQLite (le scan peut continuer pendant
que Chrome travaille) ; ce qui est scanné entre-temps sera publié à la prochaine fois.
"""
import logging
import threading

from .. import db
from ..market import lister

log = logging.getLogger(__name__)


class PublishJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = self._idle()

    @staticmethod
    def _idle() -> dict:
        return {"state": "idle", "total": 0, "done": 0, "current": None, "errors": [], "stopped": None,
                "dry_run": False}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "errors": list(self._state["errors"])}

    def start(self, submit: bool, limit: int | None = None) -> bool:
        """False si une publication est déjà en cours."""
        with self._lock:
            if self.running:
                return False
            self._cancel.clear()
            self._state = {**self._idle(), "state": "running", "dry_run": not submit}
            self._thread = threading.Thread(target=self._run, args=(submit, limit), daemon=True, name="publish")
            self._thread.start()
            return True

    def stop(self) -> None:
        """Arrêt propre : la carte en cours se termine, les suivantes ne sont pas publiées."""
        self._cancel.set()

    def _on_event(self, event: dict) -> None:
        with self._lock:
            kind = event["event"]
            if kind == "start":
                self._state["total"] = event["cards"]
            elif kind == "published":
                self._state["done"] += event["amount"]
                self._state["current"] = event["label"]
            elif kind == "error":
                self._state["errors"].append({"label": event["label"], "message": event["message"]})
            elif kind == "end":
                self._state.update(state="done", stopped=event["stopped"], current=None)

    def _run(self, submit: bool, limit: int | None) -> None:
        con = db.connect()
        try:
            lister.run(con, submit=submit, limit=limit, report=self._on_event, cancel=self._cancel)
        except Exception as e:  # imprévu (Chrome fermé, réseau…) : on le montre dans l'interface
            log.exception("publication interrompue")
            with self._lock:
                self._state.update(state="done", stopped=f"Erreur inattendue : {e}", current=None)
        finally:
            con.close()
