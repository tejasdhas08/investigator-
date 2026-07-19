"""Single source of truth for every pipeline threshold (ARCHITECTURE.md Stage 2)."""

PERSON_DET_CONF = 0.45
OBJECT_DET_CONF = 0.55
WEAPON_DET_CONF = 0.40
WEAPON_REVIEW_BELOW = 0.60
FACE_DET_CONF = 0.50
FACE_MIN_PX = 40
GENDER_CONF_MIN = 0.80
REID_MERGE_COS = 0.60
APPEARANCE_MERGE_COS = 0.85
SUSPECT_MATCH_COS = 0.65
SUSPECT_POSSIBLE_COS = 0.50
REVIEW_BAND = (0.40, 0.70)          # [low, high): requires_human_review
INTERACTION_PROXIMITY_WIDTHS = 1.5   # boxes within 1.5x person-width
INTERACTION_MIN_SECONDS = 0.6
INTERACTION_CONF_CAP = 0.75          # pipeline never claims near-certainty about intent
ACTOR_DIRECTION_SPEED_RATIO = 1.3    # >=30% faster approach → actor resolved
RUN_SPEED = 0.25                     # normalized widths/sec
WALK_SPEED = 0.05
LOITER_SECONDS = 120
LOITER_REGION_FRACTION = 0.10
PERSON_DOWN_SECONDS = 5
DISPERSAL_WINDOW_S = 2
DISPERSAL_MIN_PERSONS = 3
MAX_TRACKED_PERSONS = 30
LOW_LIGHT_LUMA = 40
LOW_LIGHT_MIN_SECONDS = 5
BLUR_LAPLACIAN_VAR = 50
BLUR_FRAME_FRACTION = 0.30
SCENE_CUT_THRESHOLD = 27.0

# Lite backend (dlib euclidean metric on 128-d embeddings; same-person guidance < 0.6).
# Conservative: match threshold well inside the same-person band; the "possible" band
# runs to dlib's published boundary and is always review-gated in the UI.
LITE_MATCH_MAX_DIST = 0.45
LITE_POSSIBLE_MAX_DIST = 0.60
LITE_REID_MAX_DIST = 0.55

WEAPON_CLASSES = {"knife", "pistol", "rifle", "baseball bat", "scissors"}
COCO_OBJECT_CLASSES = {
    "knife", "backpack", "handbag", "bottle", "cell phone", "baseball bat",
    "scissors", "car", "truck",
}


def review_flag(confidence: float) -> bool:
    return REVIEW_BAND[0] <= confidence < REVIEW_BAND[1]
