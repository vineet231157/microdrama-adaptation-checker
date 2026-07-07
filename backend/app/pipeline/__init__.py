"""The 5-step Super Pipeline.

step1_srt        — auto-crop + PaddleOCR subtitle extraction
step2_screenplay — Gemini multimodal video → director-ready screenplay
step3_merge      — stitch per-episode screenplays into one master document
step4_format     — deterministic formatter + screenplay PDF (Model 4)
step5_evaluate   — AI adaptation evaluator + PDF report (Model 5)
"""
