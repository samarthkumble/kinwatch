from datetime import datetime

from kinwatch.rules import IST, RoutineConfig, evaluate, summarize


def ms(hhmm: str, day=(2026, 10, 19)) -> int:
    h, m = map(int, hhmm.split(":"))
    return int(datetime(*day, h, m, tzinfo=IST).timestamp() * 1000)


def ev(i, hhmm, label, **vision):
    v = {"label": label, "description": f"{label} at the door",
         "person_visible": label == "person", "package_visible": label == "package", **vision}
    return {"id": f"e{i}", "device_name": "Front Door", "start_ms": ms(hhmm),
            "kw_label": label, "vision": v}


def rules_fired(events, now):
    return sorted(a.rule for a in evaluate(events, ms(now), RoutineConfig()))


def test_quiet_morning_before_deadline_no_alert():
    assert rules_fired([], "09:30") == []


def test_no_activity_after_deadline_alerts():
    alerts = evaluate([ev(1, "08:00", "animal")], ms("10:05"))
    assert [a.rule for a in alerts] == ["no_activity"]
    assert "10:05" in alerts[0].message


def test_parent_seen_means_no_activity_alert():
    assert rules_fired([ev(1, "07:40", "person")], "10:05") == []


def test_package_waiting_too_long_alerts():
    events = [ev(1, "07:40", "person"), ev(2, "08:00", "package")]
    assert rules_fired(events, "08:50") == []                       # only 50 min
    assert rules_fired(events, "09:05") == ["package_waiting"]      # 65 min


def test_package_collected_clears_alert():
    events = [ev(1, "07:40", "person"), ev(2, "08:00", "package"),
              ev(3, "08:30", "person", package_visible=False)]
    assert rules_fired(events, "09:30") == []


def test_night_visitor_alerts_but_birds_do_not():
    events = [ev(1, "07:40", "person"), ev(2, "23:15", "person"), ev(3, "23:20", "animal")]
    assert rules_fired(events, "23:30") == ["night_visitor"]


def test_alert_keys_are_stable_for_dedupe():
    events = [ev(1, "07:40", "person"), ev(2, "08:00", "package")]
    a1 = evaluate(events, ms("09:05"))[0]
    a2 = evaluate(events, ms("09:40"))[0]
    assert a1.key == a2.key == "package_waiting:e2"


def test_summary_counts_noise():
    events = [ev(1, "07:40", "person"), ev(2, "08:10", "animal"), ev(3, "08:20", "nothing")]
    s = summarize(events, ms("12:00"))
    assert s["events"] == 3 and s["ignored_as_noise"] == 2


def test_birds_later_do_not_count_as_package_collected():
    events = [ev(1, "07:40", "person"), ev(2, "08:00", "package"), ev(3, "08:20", "animal")]
    assert rules_fired(events, "09:05") == ["package_waiting"]
