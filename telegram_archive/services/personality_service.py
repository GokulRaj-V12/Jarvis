"""
Personality Service — dynamic personality profiling.
Analyzes logs over time and builds/updates a personality snapshot.
"""
import json
from services import memory_service, llm_service


async def build_context(user_id: int) -> str:
    """Build a full context string from personality + goals + recent logs."""
    parts = []

    # Personality
    personality = memory_service.get_personality(user_id)
    if personality and personality.get("summary"):
        parts.append(f"## Personality Profile\n{personality['summary']}")

    # Goals
    goals = memory_service.get_active_goals(user_id)
    if goals:
        goal_text = "\n".join([f"- {g['title']}: {g['description']}" for g in goals])
        parts.append(f"## Active Goals\n{goal_text}")

    # Recent logs
    logs = memory_service.get_recent_logs(user_id, days=5)
    if logs:
        log_text = "\n".join([f"[{l['date']}] {l['content']}" for l in logs])
        parts.append(f"## Recent Activity\n{log_text}")

    # Streak
    streak = memory_service.get_streak(user_id)
    if streak["total_logs"] > 0:
        parts.append(
            f"## Streak\n🔥 Current: {streak['current_streak']} days | "
            f"Best: {streak['longest_streak']} days | "
            f"Total logs: {streak['total_logs']}"
        )

    return "\n\n".join(parts)


async def update_personality(user_id: int) -> str:
    """Analyze recent logs and update the user's personality profile."""
    logs = memory_service.get_recent_logs(user_id, days=14)
    if not logs:
        return "Not enough data yet. Keep logging daily!"

    log_text = "\n".join([f"[{l['date']}] {l['content']} (mood: {l['mood']}, blockers: {l['blockers']})" for l in logs])

    current = memory_service.get_personality(user_id)
    current_summary = current["summary"] if current else "No profile yet."

    prompt = f"""Analyze these daily logs and create/update a personality profile.

Current profile: {current_summary}

Recent logs (last 14 days):
{log_text}

Return a JSON object with these fields:
- motivation_style: what motivates this person (1-2 sentences)
- thinking_style: how they approach problems (1-2 sentences)
- weakness_patterns: recurring struggles or blockers (1-2 sentences)
- energy_cycles: when they're most/least productive (1-2 sentences)
- work_habits: how they work best (1-2 sentences)
- summary: a 3-4 sentence overview of this person

Return ONLY valid JSON, no markdown formatting."""

    response = await llm_service.generate(
        prompt,
        system="You are a psychologist AI analyzing behavioral patterns. Return only valid JSON."
    )

    try:
        # Clean up response - remove markdown code fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]  # remove first line
            clean = clean.rsplit("```", 1)[0]  # remove last fence

        profile = json.loads(clean)
        memory_service.save_personality(user_id, profile)
        return f"Profile updated! Here's what I see:\n\n{profile.get('summary', 'Updated.')}"
    except (json.JSONDecodeError, Exception) as e:
        # If JSON parsing fails, save raw summary
        memory_service.save_personality(user_id, {"summary": response})
        return f"Profile updated with new insights."


async def generate_weekly_summary(user_id: int) -> str:
    """Generate a weekly summary of progress."""
    logs = memory_service.get_recent_logs(user_id, days=7)
    if not logs:
        return "No logs this week yet!"

    goals = memory_service.get_active_goals(user_id)
    streak = memory_service.get_streak(user_id)

    log_text = "\n".join([f"[{l['date']}] {l['content']}" for l in logs])
    goal_text = "\n".join([f"- {g['title']}" for g in goals]) if goals else "No active goals"

    context = f"""Weekly logs:\n{log_text}\n\nActive goals:\n{goal_text}\n\n🔥 Streak: {streak['current_streak']} days"""

    prompt = """Generate a brief weekly summary for the user. Include:
1. What went well (1-2 bullet points)
2. What needs work (1-2 bullet points)
3. Score out of 10 for consistency
4. One encouraging line

Keep it short and punchy. Golden retriever energy."""

    return await llm_service.generate(prompt, context=context)
