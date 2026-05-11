from __future__ import annotations
import random
from enum import Enum


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    EXCITED = "excited"
    THINKING = "thinking"
    CONFUSED = "confused"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    LAUGHING = "laughing"
    LOVE = "love"
    SLEEPY = "sleepy"
    COOL = "cool"
    FIRE = "fire"
    PARTY = "party"
    CRY = "cry"


EMOJI_MAP = {
    Emotion.NEUTRAL: "🗿",
    Emotion.HAPPY: "😊",
    Emotion.EXCITED: "🎉",
    Emotion.THINKING: "🤔",
    Emotion.CONFUSED: "😕",
    Emotion.SAD: "😢",
    Emotion.ANGRY: "😠",
    Emotion.SURPRISED: "😮",
    Emotion.LAUGHING: "😂",
    Emotion.LOVE: "❤️",
    Emotion.SLEEPY: "😴",
    Emotion.COOL: "😎",
    Emotion.FIRE: "🔥",
    Emotion.PARTY: "🥳",
    Emotion.CRY: "😭",
}

EMOTION_COLORS = {
    Emotion.NEUTRAL: "#a1a1aa",
    Emotion.HAPPY: "#22c55e",
    Emotion.EXCITED: "#f59e0b",
    Emotion.THINKING: "#6366f1",
    Emotion.CONFUSED: "#f97316",
    Emotion.SAD: "#3b82f6",
    Emotion.ANGRY: "#ef4444",
    Emotion.SURPRISED: "#a855f7",
    Emotion.LAUGHING: "#84cc16",
    Emotion.LOVE: "#ec4899",
    Emotion.SLEEPY: "#6b7280",
    Emotion.COOL: "#06b6d4",
    Emotion.FIRE: "#f97316",
    Emotion.PARTY: "#eab308",
    Emotion.CRY: "#60a5fa",
}


def detect_emotion(text: str) -> Emotion:
    """Detect emotion from text content. Args: text (str): Input text"""
    t = text.lower()
    joy_words = ("haha", "lol", "nice", "great", "awesome", "amazing", "love", "wonderful", "fantastic", "excellent", "yay", "woohoo", "glad", "happy")
    sad_words = ("sorry", "sad", "unfortunately", "apologize", "regret", "alas", "unfortunately", "afraid", "bad news")
    confused_words = ("confuse", "unclear", "not sure", "don't understand", "what", "hmm", "maybe", "perhaps")
    thinking_words = ("let me", "think", "consider", "analyze", "look into", "check", "figure", "research")
    excited_words = ("wow", "incredible", "awesome", "amazing", "congratulations", "congrats", "great", "perfect")

    if any(w in t for w in joy_words):
        return Emotion.HAPPY
    if any(w in t for w in excited_words):
        return Emotion.EXCITED
    if any(w in t for w in sad_words):
        return Emotion.SAD
    if any(w in t for w in confused_words):
        return Emotion.CONFUSED
    if any(w in t for w in thinking_words):
        return Emotion.THINKING
    return Emotion.NEUTRAL


class MoodTracker:
    def __init__(self, history_size: int = 10):
        self._history: list[Emotion] = []
        self._size = history_size

    def record(self, emotion: Emotion):
        self._history.append(emotion)
        if len(self._history) > self._size:
            self._history.pop(0)

    @property
    def current(self) -> Emotion:
        if not self._history:
            return Emotion.NEUTRAL
        return self._history[-1]

    @property
    def dominant(self) -> Emotion:
        if not self._history:
            return Emotion.NEUTRAL
        return max(set(self._history), key=self._history.count)

    @property
    def variety(self) -> int:
        return len(set(self._history))

    def summary(self) -> list[dict]:
        return [
            {"emotion": e.value, "emoji": EMOJI_MAP.get(e, ""), "color": EMOTION_COLORS.get(e, "#a1a1aa")}
            for e in self._history[-self._size:]
        ]

    def reset(self):
        self._history.clear()
