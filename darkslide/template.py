"""Slot templates: which presets exist and which edits are open.

Opening more slots means shipping a new template file, not changing code.
"""
import json

from .paths import TEMPLATE_ROOT

STAGES = ("closed", "later", "test", "open")
EDITABLE = ("test", "open")


class TemplateError(ValueError):
    pass


def load(name="gr3_v210.json"):
    value = json.loads((TEMPLATE_ROOT / name).read_text(encoding="utf-8"))
    validate(value)
    return value


def validate(value):
    def need(cond, msg):
        if not cond:
            raise TemplateError(msg)

    need(value.get("schema") == 1, "unknown template schema")
    slots = value.get("slots")
    need(isinstance(slots, list) and slots, "template has no slots")
    seen = set()
    for slot in slots:
        need(isinstance(slot.get("no"), int) and slot["no"] not in seen, "slot numbers must be unique ints")
        seen.add(slot["no"])
        need(slot.get("icon") in STAGES and slot.get("rename") in STAGES, "slot %s: bad stage" % slot["no"])
        need(isinstance(slot.get("factory_en"), str) and slot["factory_en"], "slot %s: factory_en missing" % slot["no"])
    for item in value.get("official_inputs", []):
        need(len(item.get("sha256", "")) == 64, "official input sha256 malformed")


def slot(template, no):
    for item in template["slots"]:
        if item["no"] == no:
            return item
    raise KeyError(no)


def can_edit(template, no, what):
    return slot(template, no)[what] in EDITABLE
