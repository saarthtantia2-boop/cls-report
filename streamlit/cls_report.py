import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime

# ===== School timetable (edit if needed) =====
PERIODS = [
    ("8:00",  "8:30"),
    ("8:30",  "9:05"),
    ("9:05",  "9:40"),
    ("9:40",  "10:10"),
    ("10:10", "10:45"),
    ("10:45", "11:20"),
    ("11:20", "11:55"),
    ("11:55", "12:30"),
    ("12:30", "1:00"),
    ("1:00",  "1:35"),
    ("1:35",  "2:10"),
]

st.set_page_config(page_title="Classroom Noise Report", layout="wide")
st.title("Classroom Noise Report")
st.caption("Upload the .log files from the SD card (they contain noise levels logged every second).")

def parse_time(t):
    parts = t.split(":")
    if len(parts) < 2:
        return None
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2]) if len(parts) > 2 else 0
    return hh * 3600 + mm * 60 + ss

def parse_log(raw_bytes, filename):
    text = raw_bytes.decode("utf-8", errors="ignore")
    date = None
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 1 and "-" in parts[0]:
            date = parts[0]
            continue
        if len(parts) == 2 and len(parts[0]) == 8 and parts[0][2] == ":":
            sec = parse_time(parts[0])
            if sec is not None:
                try:
                    rows.append((sec, int(parts[1])))
                except ValueError:
                    pass
    return date, rows

uploaded = st.file_uploader(
    "Select one or more .log files", type="log", accept_multiple_files=True
)

if not uploaded:
    st.info("No files yet — upload logs to see the report.")
    st.stop()

records = []
for f in uploaded:
    date, rows = parse_log(f.getvalue(), f.name)
    if not date:
        date = "unknown"
    for sec, noise in rows:
        records.append({"Date": date, "TimeSec": sec, "Noise": noise})

if not records:
    st.error("No valid noise lines found in the uploaded files.")
    st.stop()

df = pd.DataFrame(records)
dates = sorted(df["Date"].unique())

col1, col2 = st.columns([1, 3])
with col1:
    date_sel = st.selectbox("Date", dates)
    period_labels = {i: f"P{i+1} ({s} - {e})" for i, (s, e) in enumerate(PERIODS)}
    period_sel = st.selectbox("Period", list(period_labels.keys()),
                              format_func=lambda k: period_labels[k])
    show_all = st.button("Show full day instead")

day = df[df["Date"] == date_sel].copy()

st.subheader(f"Average noise per period — {date_sel}")
rows_summary = []
for i, (s, e) in enumerate(PERIODS):
    s_sec, e_sec = parse_time(s), parse_time(e)
    seg = day[(day["TimeSec"] >= s_sec) & (day["TimeSec"] < e_sec)]
    if len(seg) > 0:
        rows_summary.append({
            "Period": f"P{i+1}",
            "Avg": round(seg["Noise"].mean(), 2),
            "Max": int(seg["Noise"].max()),
        })
summary = pd.DataFrame(rows_summary)
if len(summary) > 0:
    bar_chart = alt.Chart(summary).mark_bar(color="#4c78a8", width=30).encode(
        x=alt.X("Period:N", title="Period"),
        y=alt.Y("Avg:Q", scale=alt.Scale(domain=[0, 15]), title="Avg Noise"),
        tooltip=["Period", "Avg", "Max"],
    ).properties(height=300)
    st.altair_chart(bar_chart, use_container_width=True)
else:
    st.info("No period data available.")

s_sec = parse_time(PERIODS[period_sel][0])
e_sec = parse_time(PERIODS[period_sel][1])
if show_all:
    seg = day
    title = "Full day"
else:
    seg = day[(day["TimeSec"] >= s_sec) & (day["TimeSec"] < e_sec)]
    title = f"Period P{period_sel+1} ({PERIODS[period_sel][0]} - {PERIODS[period_sel][1]})"

st.subheader(f"Noise over time — {title}")

if len(seg) == 0:
    st.info("No data in this time range.")
else:
    seg = seg.copy()
    seg["Clock"] = seg["TimeSec"].apply(lambda s: f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}")

    min_sec = int(seg["TimeSec"].min())
    max_sec = int(seg["TimeSec"].max())
    total_range = max_sec - min_sec

    zoom_options = {
        "10 min": 600, "5 min": 300, "1 min": 60, "30 sec": 30, "10 sec": 10,
    }
    col_a, col_b = st.columns([1, 3])
    with col_a:
        zoom_label = st.selectbox("Zoom", list(zoom_options.keys()), index=0)
    window = zoom_options[zoom_label]
    if window > total_range:
        window = total_range

    with col_b:
        pos = st.slider("Position", min_value=0, max_value=max(total_range, 1),
                        value=0, step=1,
                        format_func=lambda s: f"{(min_sec+s)//3600:02d}:{((min_sec+s)%3600)//60:02d}:{(min_sec+s)%60:02d}")

    start = min_sec + pos
    end = start + window
    view = seg[(seg["TimeSec"] >= start) & (seg["TimeSec"] <= end)]

    if len(view) == 0:
        st.info("No data in this zoom window. Slide to a different position.")
    else:
        if window <= 60:
            label_each = 1
        elif window <= 300:
            label_each = 5
        else:
            label_each = 5

        view = view.copy()
        view["Label"] = view["TimeSec"].apply(
            lambda s: f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if (s - start) % label_each == 0 else ""
        )
        chart = alt.Chart(view).mark_bar(color="#ff4b4b").encode(
            x=alt.X("Label:N", title="Time", sort=None,
                     axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("Noise:Q", scale=alt.Scale(domain=[0, 15], domainMin=0), title="Noise level"),
        ).properties(height=320)
        st.altair_chart(chart, use_container_width=True)

        st.metric("Average noise", f"{view['Noise'].mean():.2f}", help="Average noise level in this window")
        st.metric("Peak noise", f"{view['Noise'].max()}")