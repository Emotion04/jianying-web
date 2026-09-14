"""
Video Template Registry
"""

from .product_intro import ProductIntroTemplate
from .vlog import VlogTemplate

TEMPLATE_REGISTRY = {
    "product_intro": ProductIntroTemplate(),
    "vlog": VlogTemplate(),
}
