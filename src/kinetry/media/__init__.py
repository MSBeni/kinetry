"""Generated media for videos: images, video clips and character sprite packs from paid model services.

Everything here is opt-in and uses the caller's own account (bring your own key). Each provider call goes
through three guards:

- an estimate before anything is generated (`kinetry.media.pricing`), so a run can be priced and refused;
- a per-run spending cap (`Budget`): a call that would go over it is never made;
- a content-addressed cache (`MediaCache`): the same request is only ever paid for once, and a finished
  run can be re-rendered with no model calls.

Providers: `google` (Gemini image models and Imagen for images, Veo for video, on Vertex AI or the Gemini
API). Avatar services (HeyGen, Hedra, Tavus, Runway) plug in through the same protocols.
"""

from .base import Budget, BudgetExceeded, MediaCache, MediaError, MediaResult
from .pricing import estimate_image, estimate_video

__all__ = [
    "Budget",
    "BudgetExceeded",
    "MediaCache",
    "MediaError",
    "MediaResult",
    "estimate_image",
    "estimate_video",
]
