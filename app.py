import os
import tempfile
import sqlite3
from datetime import datetime, timedelta

import streamlit as st
from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh

# -------------------------
# PAGE CONFIG
# -------------------------
st.set_page_config(
    page_title="Employee Engagement Scrabble Game",
    page_icon="🧩",
    layout="centered",
)

# Detect admin view via URL parameter (?admin=1)
IS_ADMIN_VIEW = False
try:
    # Newer Streamlit versions
    IS_ADMIN_VIEW = st.query_params.get("admin", "0") == "1"
except Exception:
    # Fallback for older versions
    params = st.experimental_get_query_params()
    IS_ADMIN_VIEW = params.get("admin", ["0"])[0] == "1"

# Admin PIN (change to your own secret code)
ADMIN_PIN = "hradmin"

# SQLite DB path in a guaranteed writable temp directory
DB_PATH = os.path.join(tempfile.gettempdir(), "engagement_scrabble.db")

# 13 SCRABBLE WORDS + CLUES
WORDS = [
    {
        "index": 0,
        "scramble": "GNEGAEMNET",
        "answer": "ENGAGEMENT",
        "clue": "Emotional commitment employees feel towards their organisation.",
    },
    {
        "index": 1,
        "scramble": "WELNLEBIEG",
        "answer": "WELLBEING",
        "clue": "Employee health, happiness and overall state at work.",
    },
    {
        "index": 2,
        "scramble": "IVYITFLEXLBI",
        "answer": "FLEXIBILITY",
        "clue": "Ability to choose when or where to work.",
    },
    {
        "index": 3,
        "scramble": "EALHEDRIPS",
        "answer": "LEADERSHIP",
        "clue": "Guiding and influencing others towards shared goals.",
    },
    {
        "index": 4,
        "scramble": "TSAURT",
        "answer": "TRUST",
        "clue": "Belief that managers and colleagues act fairly.",
    },
    {
        "index": 5,
        "scramble": "HYBRDIROWK",
        "answer": "HYBRIDWORK",
        "clue": "Mix of office and remote work locations.",
    },
    {
        "index": 6,
        "scramble": "LEARNGNIE",
        "answer": "LEARNING",
        "clue": "Building new skills and knowledge.",
    },
    {
        "index": 7,
        "scramble": "ECTFEEBDKAB",
        "answer": "FEEDBACK",
        "clue": "Information given to help improve performance.",
    },
    {
        "index": 8,
        "scramble": "LUUTRECC",
        "answer": "CULTURE",
        "clue": "Shared values, norms and habits inside the organisation.",
    },
    {
        "index": 9,
        "scramble": "MOTIOTVANI",
        "answer": "MOTIVATION",
        "clue": "Inner drive that makes people want to do their job well.",
    },
    {
        "index": 10,
        "scramble": "AUTYMONO",
        "answer": "AUTONOMY",
        "clue": "Freedom to decide how to do your work.",
    },
    {
        "index": 11,
        "scramble": "INCUSOINL",
        "answer": "INCLUSION",
        "clue": "Everyone feels welcome and respected.",
    },
    {
        "index": 12,
        "scramble": "REIONCOINGT",
        "answer": "RECOGNITION",
        "clue": "Appreciating and thanking employees for contributions.",
    },
]

TOTAL_WORDS = len(WORDS)
TIME_LIMIT = 30  # seconds per word
ACTIVE_WINDOW_MINUTES = 10  # for live participants counter


# -------------------------
# DB HELPERS
# -------------------------
@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = 1")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Players table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP
        )
        """
    )

    # Scores table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            word_index INTEGER NOT NULL,
            correct INTEGER NOT NULL,
            time_taken REAL,
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(player_id, word_index),
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
        """
    )

    # Global game state (single row, id = 1)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_word_index INTEGER NOT NULL DEFAULT 0,
            question_start_time TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Ensure the single game_state row exists
    cur.execute(
        """
        INSERT OR IGNORE INTO game_state (id, current_word_index, is_active)
        VALUES (1, 0, 0)
        """
    )

    conn.commit()


def get_game_state():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT current_word_index, question_start_time, is_active FROM game_state WHERE id = 1"
    )
    row = cur.fetchone()
    if not row:
        return {"current_word_index": 0, "question_start_time": None, "is_active": 0}

    idx, q_time, is_active = row
    if q_time:
        if isinstance(q_time, str):
            start_dt = datetime.fromisoformat(q_time)
        else:
            start_dt = q_time
    else:
        start_dt = None

    return {
        "current_word_index": idx,
        "question_start_time": start_dt,
        "is_active": bool(is_active),
    }


def set_game_state(current_word_index=None, question_start_time=None, is_active=None):
    conn = get_connection()
    cur = conn.cursor()

    fields = []
    params = []
    if current_word_index is not None:
        fields.append("current_word_index = ?")
        params.append(current_word_index)
    if question_start_time is not None:
        fields.append("question_start_time = ?")
        params.append(question_start_time)
    if is_active is not None:
        fields.append("is_active = ?")
        params.append(int(is_active))

    if fields:
        sql = f"UPDATE game_state SET {', '.join(fields)} WHERE id = 1"
        cur.execute(sql, tuple(params))
        conn.commit()


def get_or_create_player(name: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM players WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        player_id = row[0]
    else:
        cur.execute(
            "INSERT INTO players (name, last_seen) VALUES (?, ?)",
            (name, datetime.utcnow()),
        )
        conn.commit()
        player_id = cur.lastrowid

    return player_id


def update_last_seen(player_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?",
        (datetime.utcnow(), player_id),
    )
    conn.commit()


def count_live_players():
    conn = get_connection()
    cur = conn.cursor()
    cutoff = datetime.utcnow() - timedelta(minutes=ACTIVE_WINDOW_MINUTES)
    cur.execute(
        "SELECT COUNT(*) FROM players WHERE last_seen >= ?",
        (cutoff,),
    )
    return cur.fetchone()[0]


def get_live_players_names():
    conn = get_connection()
    cur = conn.cursor()
    cutoff = datetime.utcnow() - timedelta(minutes=ACTIVE_WINDOW_MINUTES)
    cur.execute(
        "SELECT name FROM players WHERE last_seen >= ? ORDER BY name COLLATE NOCASE",
        (cutoff,),
    )
    rows = cur.fetchall()
    return [r[0] for r in rows]


def save_score(player_id: int, word_index: int, correct: bool, time_taken: float | None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO scores (player_id, word_index, correct, time_taken, answered_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (player_id, word_index, int(correct), time_taken, datetime.utcnow()),
    )
    conn.commit()


def get_overall_leaderboard():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.name,
            COALESCE(SUM(CASE WHEN s.correct = 1 THEN 1 ELSE 0 END), 0) AS correct_answers,
            COALESCE(SUM(CASE WHEN s.correct = 1 THEN s.time_taken ELSE 0 END), 0.0) AS total_time
        FROM players p
        LEFT JOIN scores s ON p.id = s.player_id
        GROUP BY p.id
        ORDER BY correct_answers DESC, total_time ASC
        """
    )
    return cur.fetchall()


def get_current_word_leaderboard(word_index: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.name, s.time_taken
        FROM scores s
        JOIN players p ON p.id = s.player_id
        WHERE s.word_index = ? AND s.correct = 1
        ORDER BY s.time_taken ASC
        """,
        (word_index,),
    )
    return cur.fetchall()


def get_answer_stats(word_index: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) AS correct_count
        FROM scores
        WHERE word_index = ?
        """,
        (word_index,),
    )
    row = cur.fetchone()
    total = row[0] if row and row[0] is not None else 0
    correct = row[1] if row and row[1] is not None else 0
    incorrect = total - correct
    return total, correct, incorrect


def reset_all():
    """Delete all scores, all players, and reset game_state to initial."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM scores")
    cur.execute("DELETE FROM players")
    cur.execute(
        """
        UPDATE game_state
        SET current_word_index = 0,
            question_start_time = NULL,
            is_active = 0
        WHERE id = 1
        """
    )
    conn.commit()


def player_exists(player_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM players WHERE id = ?", (player_id,))
    return cur.fetchone() is not None


# -------------------------
# SESSION STATE
# -------------------------
def init_session_state():
    if "player_name" not in st.session_state:
        st.session_state.player_name = None
    if "player_id" not in st.session_state:
        st.session_state.player_id = None
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    if "seen_word_index" not in st.session_state:
        st.session_state.seen_word_index = -1
    if "has_answered" not in st.session_state:
        st.session_state.has_answered = False
    if "last_answer_correct" not in st.session_state:
        st.session_state.last_answer_correct = None
    if "last_answer_time" not in st.session_state:
        st.session_state.last_answer_time = None


# -------------------------
# ADMIN CONTROLS & INSIGHTS (SIDEBAR)
# -------------------------
def render_admin_controls():
    if not IS_ADMIN_VIEW:
        return

    with st.sidebar.expander("🧑‍🏫 Host / Admin controls", expanded=True):
        live_players_admin = count_live_players()
        st.metric("Live participants", live_players_admin)

        if not st.session_state.is_admin:
            pin = st.text_input("Enter admin PIN:", type="password", key="admin_pin")
            if st.button("Unlock admin", key="unlock_admin"):
                if pin == ADMIN_PIN:
                    st.session_state.is_admin = True
                    st.success("Admin controls unlocked.")
                    st.rerun()
                else:
                    st.error("Incorrect PIN.")
        else:
            st.success("Admin mode active ✅")

            game_state = get_game_state()
            idx = game_state["current_word_index"]
            start_time = game_state["question_start_time"]
            is_active = game_state["is_active"]

            if idx < TOTAL_WORDS:
                word_data = WORDS[idx]
                st.markdown(f"### 🎯 Current word: **{idx + 1} / {TOTAL_WORDS}**")
                st.write(f"Scramble: `{word_data['scramble']}`")
                st.write(f"Clue: {word_data['clue']}")
            else:
                st.write("All words completed.")

            if start_time:
                now = datetime.utcnow()
                elapsed = (now - start_time).total_seconds()
                time_elapsed = int(elapsed)
                time_left = max(0, TIME_LIMIT - time_elapsed)
            else:
                time_elapsed = 0
                time_left = 0

            tcol1, tcol2 = st.columns(2)
            with tcol1:
                st.metric("⏱ Elapsed (s)", time_elapsed)
            with tcol2:
                st.metric("⏱ Remaining (s)", time_left)

            if idx < TOTAL_WORDS and start_time is not None and time_left <= 0:
                st.markdown(f"✅ Correct word: **{WORDS[idx]['answer']}**")
            elif idx < TOTAL_WORDS:
                st.caption("Correct word will appear here after time is over.")

            if not is_active or start_time is None:
                names = get_live_players_names()
                st.markdown("**✅ Logged-in players (waiting):**")
                if names:
                    st.write(", ".join(names))
                else:
                    st.write("No players have joined yet.")

            if idx < TOTAL_WORDS:
                total_ans, correct_ans, incorrect_ans = get_answer_stats(idx)
                st.markdown("**📊 This word stats:**")
                st.write(f"- Total answers: **{total_ans}**")
                st.write(f"- Correct: **{correct_ans}**")
                st.write(f"- Incorrect: **{incorrect_ans}**")

            st.markdown("---")
            if idx < TOTAL_WORDS:
                st.markdown("### 🎮 Round controls")
                if not is_active:
                    if st.button("▶️ Start round (30 seconds)", key="admin_start_round"):
                        set_game_state(
                            question_start_time=datetime.utcnow(), is_active=1
                        )
                        st.rerun()
                else:
                    st.info("Round is currently in progress.")
                    if st.button("⏹ Stop round (lock answers)", key="admin_stop_round"):
                        set_game_state(is_active=0)
                        st.rerun()

                if st.button("⏭ Next word", key="admin_next_word"):
                    new_idx = min(idx + 1, TOTAL_WORDS)
                    set_game_state(
                        current_word_index=new_idx,
                        question_start_time=None,
                        is_active=0,
                    )
                    st.rerun()

            st.markdown("---")
            st.markdown("### 🌈 Live Overall Leaderboard")

            rows = get_overall_leaderboard()
            if rows:
                max_correct = max(int(r[1]) for r in rows) or 1
                for rank, (name, correct_count, total_time) in enumerate(
                    rows[:5], start=1
                ):
                    correct_count = int(correct_count)
                    total_time = round(total_time, 2)

                    if rank == 1:
                        bg = "#FFD700"
                        medal = "🥇"
                    elif rank == 2:
                        bg = "#C0C0C0"
                        medal = "🥈"
                    elif rank == 3:
                        bg = "#CD7F32"
                        medal = "🥉"
                    else:
                        bg = "#E3F2FD"
                        medal = "⭐"

                    fill = int((correct_count / max_correct) * 100)

                    st.markdown(
                        f"""
                        <div style="
                            background-color:{bg};
                            border-radius:10px;
                            padding:8px 10px;
                            margin-bottom:6px;
                            border:1px solid #ddd;
                        ">
                            <strong>{medal} {rank}. {name}</strong><br>
                            Correct: {correct_count} &nbsp;|&nbsp; Total time: {total_time}s
                            <div style="background-color:#ffffff80; border-radius:6px; margin-top:4px;">
                                <div style="
                                    width:{fill}%;
                                    background-color:#1E88E5;
                                    height:6px;
                                    border-radius:6px;
                                "></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.write("No scores yet. Be the first to answer!")

            if idx < TOTAL_WORDS:
                st.markdown("### ⚡ Fastest on this word")
                word_rows = get_current_word_leaderboard(idx)
                if word_rows:
                    for rank, (name, time_taken) in enumerate(word_rows[:5], start=1):
                        time_taken = round(time_taken, 2)
                        if rank == 1:
                            chip_color = "#C8E6C9"
                            icon = "⚡"
                        else:
                            chip_color = "#FFF9C4"
                            icon = "⏱"

                        st.markdown(
                            f"""
                            <div style="
                                background-color:{chip_color};
                                border-radius:10px;
                                padding:6px 8px;
                                margin-bottom:4px;
                                border:1px solid #ddd;
                            ">
                                <strong>{icon} {rank}. {name}</strong> – {time_taken}s
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                else:
                    st.write("No correct answers for this word yet.")

            st.markdown("---")
            if st.button("🔁 Reset game (scores + players + state)", key="admin_reset"):
                reset_all()
                st.success("Game and players have been fully reset.")
                st.rerun()


# -------------------------
# LEADERBOARD & FEEDBACK
# -------------------------
def show_answer_feedback(word_data):
    correct_answer = word_data["answer"].upper()
    if st.session_state.last_answer_correct:
        st.success(
            f"✅ Correct! The word was **{correct_answer}**.\n\n"
            f"You answered in **{st.session_state.last_answer_time:.2f} seconds**."
        )
    else:
        st.error(
            f"❌ Incorrect or you ran out of time. The correct word was **{correct_answer}**."
        )

    st.markdown("### ✨ Word Reveal ✨")
    st.markdown(
        f"<h2 style='text-align:center; color:#4CAF50;'>{correct_answer}</h2>",
        unsafe_allow_html=True,
    )


def show_leaderboard_section(current_word_index: int | None = None):
    st.subheader("🏆 Leaderboard")

    rows = get_overall_leaderboard()
    if rows:
        st.markdown("**Overall ranking (all words):**")
        overall_data = []
        for rank, row in enumerate(rows, start=1):
            name, correct_answers, total_time = row
            overall_data.append(
                {
                    "Rank": rank,
                    "Player": name,
                    "Correct answers": int(correct_answers),
                    "Total time (s, correct only)": round(total_time, 2),
                }
            )
        st.table(overall_data)
    else:
        st.write("No scores yet. Be the first to answer!")

    if current_word_index is not None:
        st.markdown("**Fastest correct answers for this word:**")
        word_rows = get_current_word_leaderboard(current_word_index)
        if word_rows:
            per_word_data = []
            for rank, (name, time_taken) in enumerate(word_rows, start=1):
                per_word_data.append(
                    {
                        "Rank": rank,
                        "Player": name,
                        "Time (s)": round(time_taken, 2),
                    }
                )
            st.table(per_word_data)
        else:
            st.write("No correct answers for this word yet.")


# -------------------------
# ADMIN MAIN VIEW
# -------------------------
def show_admin_main_view():
    st.subheader("Host / Projector View")

    live_players = count_live_players()
    st.metric("Live participants", live_players)

    names = get_live_players_names()
    st.markdown("**Logged-in players (waiting):**")
    if names:
        st.write(", ".join(names))
    else:
        st.write("No players have joined yet.")

    game_state = get_game_state()
    current_index = game_state["current_word_index"]
    start_time = game_state["question_start_time"]
    is_active = game_state["is_active"]

    if current_index >= TOTAL_WORDS:
        st.markdown("### 🎉 Game over!")
        st.write("All 13 words have been completed.")
        show_leaderboard_section()
        st.info("Use the admin controls in the sidebar if you want to reset the game.")
        return

    word_data = WORDS[current_index]
    st.markdown(f"### Word {current_index + 1} of {TOTAL_WORDS}")

    if not is_active or start_time is None:
        st.info("Waiting for the host to press **Start round** in the sidebar.")
        st.markdown(
            f"""
            #### 🔤 Upcoming scrabble word
            **`{word_data['scramble']}`**
            
            💡 **Clue:** {word_data['clue']}
            """
        )
        show_leaderboard_section(current_word_index=word_data["index"])
        return

    now = datetime.utcnow()
    elapsed = (now - start_time).total_seconds()
    time_elapsed = int(elapsed)
    time_left = max(0, TIME_LIMIT - time_elapsed)

    st.markdown(
        f"""
        #### 🔤 Scrabble word
        **`{word_data['scramble']}`**
        
        💡 **Clue:** {word_data['clue']}
        """
    )

    tcol1, tcol2 = st.columns(2)
    with tcol1:
        st.metric("⏱ Elapsed (s)", time_elapsed)
    with tcol2:
        st.metric("⏱ Remaining (s)", time_left)

    if time_left <= 0:
        st.markdown("### ✅ Correct word")
        st.markdown(
            f"<h2 style='text-align:center; color:#4CAF50;'>{word_data['answer'].upper()}</h2>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Correct word will appear here after the time is over.")

    st.markdown("---")
    show_leaderboard_section(current_word_index=word_data["index"])


# -------------------------
# MAIN APP
# -------------------------
def main():
    init_db()
    init_session_state()

    # 🔁 Re-run script every 1s for realtime updates in ALL sessions
    st_autorefresh(interval=1000, key="game_autorefresh")

    st.title("🧩 Employee Engagement Scrabble – Live Game")

    render_admin_controls()

    if IS_ADMIN_VIEW:
        show_admin_main_view()
        return

    # ---- PLAYER FLOW ----
    if not st.session_state.player_name or not st.session_state.player_id:
        st.subheader("Join the game")
        name_input = st.text_input("Your display name", key="name_input")
        if st.button("Join Game"):
            name = name_input.strip()
            if not name:
                st.warning("Please enter a name.")
                st.stop()
            try:
                player_id = get_or_create_player(name)
                st.session_state.player_name = name
                st.session_state.player_id = player_id
                st.success(f"Welcome, {name}! You have joined the live game.")
                st.rerun()
            except Exception as e:
                st.error(f"Error creating player: {e}")
                st.stop()
        st.stop()

    # Player is logged in (but maybe deleted by reset)
    player_id = st.session_state.player_id
    player_name = st.session_state.player_name

    if not player_exists(player_id):
        st.session_state.player_id = None
        st.session_state.player_name = None
        st.rerun()

    update_last_seen(player_id)

    live_players = count_live_players()

    game_state = get_game_state()
    current_index = game_state["current_word_index"]
    start_time = game_state["question_start_time"]
    is_active = game_state["is_active"]

    if st.session_state.seen_word_index != current_index:
        st.session_state.seen_word_index = current_index
        st.session_state.has_answered = False
        st.session_state.last_answer_correct = None
        st.session_state.last_answer_time = None

    top_cols = st.columns([2, 1])
    with top_cols[0]:
        st.markdown(f"**Player:** {player_name}")
    with top_cols[1]:
        st.metric("Live participants", live_players)

    if current_index >= TOTAL_WORDS:
        st.subheader("🎉 Game over!")
        st.write("All 13 words have been completed.")
        show_leaderboard_section()
        st.info("Ask the host if you want to reset and play again.")
        st.stop()

    word_data = WORDS[current_index]

    st.subheader(f"Word {current_index + 1} of {TOTAL_WORDS}")

    if not is_active or start_time is None:
        st.info("Waiting for the host to press **Start round**.")
        st.markdown(
            f"""
            ### 🔤 Upcoming scrabble word:
            **`{word_data['scramble']}`**
            
            💡 **Clue:** {word_data['clue']}
            """
        )
        st.caption("You will have 30 seconds to answer after the host starts the round.")
        show_leaderboard_section(current_word_index=word_data["index"])
        st.stop()

    now = datetime.utcnow()
    elapsed = (now - start_time).total_seconds()
    time_elapsed = int(elapsed)
    time_left = max(0, TIME_LIMIT - time_elapsed)

    if time_left <= 0 and not st.session_state.has_answered:
        save_score(player_id, word_data["index"], False, None)
        st.session_state.has_answered = True
        st.session_state.last_answer_correct = False

    st.markdown(
        f"""
        ### 🔤 Scrabble word:
        **`{word_data['scramble']}`**
        
        💡 **Clue:** {word_data['clue']}
        """
    )

    timer_col1, timer_col2 = st.columns(2)
    with timer_col1:
        st.metric("⏱ Elapsed (s)", time_elapsed)
    with timer_col2:
        st.metric("⏱ Remaining (s)", time_left)

    disabled_input = st.session_state.has_answered or time_left <= 0

    answer = st.text_input(
        "Type the correct word (A–Z only, no spaces):",
        key=f"answer_input_{current_index}",
        disabled=disabled_input,
    )

    if st.button("Submit answer", disabled=disabled_input):
        now = datetime.utcnow()
        elapsed = (now - start_time).total_seconds()
        time_taken = min(elapsed, TIME_LIMIT)

        user_answer = answer.strip().upper()
        correct_answer = word_data["answer"].upper()

        is_correct = user_answer == correct_answer and time_taken <= TIME_LIMIT

        st.session_state.has_answered = True
        st.session_state.last_answer_correct = is_correct
        st.session_state.last_answer_time = time_taken if is_correct else None

        save_score(
            player_id,
            word_data["index"],
            is_correct,
            time_taken if is_correct else None,
        )

        if is_correct:
            st.balloons()

        st.rerun()

    if st.session_state.has_answered or time_left <= 0:
        show_answer_feedback(word_data)
        st.markdown("---")
        show_leaderboard_section(current_word_index=word_data["index"])
        st.caption("Wait for the host to move to the next word.")


if __name__ == "__main__":
    main()
