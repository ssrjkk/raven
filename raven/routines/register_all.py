from raven.core.routine.engine import RoutineEngine
from raven.routines.briefing import send_briefing, send_message, check_email
from raven.routines.file_watch import organize_files


def register_all_routines(engine: RoutineEngine) -> None:
    engine.register_handler("send_briefing", send_briefing)
    engine.register_handler("send_message", send_message)
    engine.register_handler("check_email", check_email)
    engine.register_handler("organize_files", organize_files)
