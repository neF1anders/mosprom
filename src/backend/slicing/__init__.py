"""Slicing (stage four) and the check of its G-code (stage five), pure like the stages before.

The plan of plugin calls and the G-code check read the parameter set and the catalog only;
the plugin itself is reached through the ``Slicer`` port.
"""

from .gcode import GcodeFacts, check_gcode, read_gcode
from .plan import build_plan

__all__ = ["GcodeFacts", "build_plan", "check_gcode", "read_gcode"]
