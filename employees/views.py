from .views_shared import *
from .views_directory import *
from .views_self_service import *
from .views_management import *
from .views_action_center import *
from .views_api import *

# This file remains the public import surface for employees URLs and templates.
# The implementation is intentionally split into grouped modules to keep the
# employee workspace maintainable as the app grows.
