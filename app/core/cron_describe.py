"""Diễn giải biểu thức cron 5 trường sang câu tiếng Việt dễ hiểu, dùng để
hiển thị cạnh ô nhập cron trong dialog Thêm/Sửa database — bản thân cron
(phút giờ ngày tháng thứ) khá kén người không quen dùng Linux/cron, nên
cần một câu mô tả bằng lời bên cạnh để người dùng biết mình vừa gõ gì.

Không thay thế việc parse/validate thật (app/core/scheduler.py dùng
APScheduler's CronTrigger.from_crontab cho việc đó) — module này chỉ sinh
mô tả, không nên tự ý coi là "hợp lệ" nếu APScheduler từ chối.
"""
from __future__ import annotations

WEEKDAY_NAMES = {
    "0": "Chủ nhật", "7": "Chủ nhật",
    "1": "Thứ 2", "2": "Thứ 3", "3": "Thứ 4",
    "4": "Thứ 5", "5": "Thứ 6", "6": "Thứ 7",
}


def _weekday_list(dow: str) -> str:
    return ", ".join(WEEKDAY_NAMES.get(d.strip(), d.strip()) for d in dow.split(","))


def _field_text(value: str, label: str) -> str:
    if value == "*":
        return f"mọi {label}"
    if value.startswith("*/"):
        return f"mỗi {value[2:]} {label}"
    if "," in value:
        return f"{label} thuộc {value}"
    if "-" in value:
        return f"{label} từ {value.replace('-', ' đến ')}"
    return f"{label} = {value}"


def describe_cron(expr: str) -> str:
    """Trả về 1 câu mô tả tiếng Việt cho biểu thức cron 5 trường
    (phút giờ ngày-trong-tháng tháng thứ-trong-tuần). Không raise — với
    input không hợp lệ, trả về câu giải thích lỗi thay vì mô tả lịch chạy.
    """
    parts = expr.split()
    if len(parts) != 5:
        return "Cần đúng 5 trường: phút giờ ngày tháng thứ (vd. 0 */6 * * *)."

    minute, hour, day, month, dow = parts

    # Mỗi N phút (bỏ qua giờ/ngày/tháng/thứ)
    if hour == "*" and day == "*" and month == "*" and dow == "*":
        if minute == "*":
            return "Chạy mỗi phút."
        if minute.startswith("*/"):
            return f"Chạy mỗi {minute[2:]} phút, suốt ngày đêm."

    # Phút cố định, ngày/tháng/thứ bỏ trống -> mỗi giờ / mỗi N giờ / hằng ngày
    if day == "*" and month == "*" and dow == "*" and minute.isdigit():
        if hour.startswith("*/"):
            return f"Chạy mỗi {hour[2:]} giờ (vào phút thứ {minute} của mỗi giờ đó)."
        if hour == "*":
            return f"Chạy mỗi giờ, vào phút thứ {minute}."
        if hour.isdigit():
            return f"Chạy hằng ngày, lúc {int(hour):02d}:{int(minute):02d}."

    # Theo (các) thứ trong tuần, giờ cố định
    if day == "*" and month == "*" and dow != "*" and minute.isdigit() and hour.isdigit():
        return f"Chạy vào {_weekday_list(dow)} hằng tuần, lúc {int(hour):02d}:{int(minute):02d}."

    # Ngày cố định trong tháng, giờ cố định
    if day.isdigit() and month == "*" and dow == "*" and minute.isdigit() and hour.isdigit():
        return f"Chạy vào ngày {int(day)} hằng tháng, lúc {int(hour):02d}:{int(minute):02d}."

    # Fallback: diễn giải từng trường một
    bits = [_field_text(minute, "phút"), _field_text(hour, "giờ")]
    if day != "*":
        bits.append(_field_text(day, "ngày trong tháng"))
    if month != "*":
        bits.append(_field_text(month, "tháng"))
    if dow != "*":
        bits.append(f"vào {_weekday_list(dow)}")
    return "Chạy khi " + ", ".join(bits) + "."
