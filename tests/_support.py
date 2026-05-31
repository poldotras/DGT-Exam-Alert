"""Test support: put app/ on sys.path and stub the heavy third-party deps that aren't
installed in this environment (selenium, telegram, sqlalchemy, pytz, sentry_sdk).

The stubs only need enough surface for the *module-level* imports in the production code
to succeed — the real objects (webdriver, Bot, engine) are never instantiated in tests;
business logic is exercised with unittest.mock doubles instead.

Every test module does `import _support  # noqa` as its first import. Importing this
module performs the installation exactly once (it is cached in sys.modules).
"""
import os
import sys
import types
from datetime import timezone

# Don't write .pyc: app/__pycache__ is owned by root (Docker bind-mount), so writing
# bytecode there raises PermissionError. Disabling keeps `python -m unittest` clean.
sys.dont_write_bytecode = True

# --- app/ on the path so `from main import ...`, `from exam_pipeline import ...` work ---
APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if APP not in sys.path:
    sys.path.insert(0, APP)


def _mod(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


def _exc(name):
    return type(name, (Exception,), {})


# --- sentry_sdk ---
sentry = _mod("sentry_sdk")
sentry.init = lambda *a, **k: None
sentry.capture_exception = lambda *a, **k: None
sentry.capture_message = lambda *a, **k: None

# --- pytz (timezone() must return a real tzinfo so datetime.now(tz) works) ---
pytz = _mod("pytz")
pytz.timezone = lambda name: timezone.utc

# --- selenium ---
selenium = _mod("selenium")
webdriver = _mod("selenium.webdriver")
selenium.webdriver = webdriver
webdriver.Chrome = lambda *a, **k: None
_common = _mod("selenium.webdriver.common")
webdriver.common = _common
_by = _mod("selenium.webdriver.common.by")
_common.by = _by
_by.By = type("By", (), {"ID": "id", "CLASS_NAME": "class name", "XPATH": "xpath", "NAME": "name"})
_chrome = _mod("selenium.webdriver.chrome")
webdriver.chrome = _chrome
_options = _mod("selenium.webdriver.chrome.options")
_chrome.options = _options
_options.Options = type("Options", (), {})
_support_mod = _mod("selenium.webdriver.support")
webdriver.support = _support_mod
_ui = _mod("selenium.webdriver.support.ui")
_support_mod.ui = _ui
_ui.WebDriverWait = lambda *a, **k: None
_ui.Select = lambda *a, **k: None
_ec = _mod("selenium.webdriver.support.expected_conditions")
_support_mod.expected_conditions = _ec
_sel_common = _mod("selenium.common")
selenium.common = _sel_common
_sel_exc = _mod("selenium.common.exceptions")
_sel_common.exceptions = _sel_exc
for _name in ("NoSuchElementException", "ElementNotInteractableException",
              "WebDriverException", "TimeoutException", "InvalidSessionIdException"):
    setattr(_sel_exc, _name, _exc(_name))

# --- telegram ---
telegram = _mod("telegram")
telegram.Bot = lambda *a, **k: None
_tg_constants = _mod("telegram.constants")
telegram.constants = _tg_constants
_tg_constants.ParseMode = type("ParseMode", (), {"HTML": "HTML"})
_tg_error = _mod("telegram.error")
telegram.error = _tg_error
for _name in ("TimedOut", "NetworkError", "ChatMigrated", "BadRequest"):
    setattr(_tg_error, _name, _exc(_name))

# --- sqlalchemy (enough for the ORM class bodies in database_manager to evaluate) ---
sqlalchemy = _mod("sqlalchemy")
sqlalchemy.create_engine = lambda *a, **k: None
sqlalchemy.Column = lambda *a, **k: None
sqlalchemy.Integer = type("Integer", (), {})
sqlalchemy.String = lambda *a, **k: None
sqlalchemy.Date = type("Date", (), {})
sqlalchemy.ForeignKey = lambda *a, **k: None
_sa_ext = _mod("sqlalchemy.ext")
sqlalchemy.ext = _sa_ext
_sa_decl = _mod("sqlalchemy.ext.declarative")
_sa_ext.declarative = _sa_decl
_sa_decl.declarative_base = lambda *a, **k: type("Base", (), {})
_sa_orm = _mod("sqlalchemy.orm")
sqlalchemy.orm = _sa_orm
_sa_orm.sessionmaker = lambda *a, **k: (lambda *a2, **k2: None)
_sa_orm.relationship = lambda *a, **k: None
_sa_orm.joinedload = lambda *a, **k: None
_sa_exc = _mod("sqlalchemy.exc")
sqlalchemy.exc = _sa_exc
_sa_exc.OperationalError = _exc("OperationalError")
