"""Semantic reasoning layer — sits between deterministic intent parsing
and the existing Agent/ActionExecutor. Only ever called once per voice
command; never touches the camera/detection/tracking real-time loops.
"""
