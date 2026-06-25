"""
Translates raw model features and SHAP contributions into the plain-language
factor breakdown consumed by the ResultPanel component on the frontend.

Sixteen model features are grouped into five user-facing factors. Each
group's SHAP contributions are summed to determine its rating, and a
human-readable detail/explanation pair is generated from the underlying
feature values.
"""

DIST_BAND_LABELS = ["within 50m", "50-150m", "150-400m", "over 400m"]

# Non-overlapping feature groups covering all 16 model features
FACTOR_GROUPS = {
    "Pedestrian Activity": [
        "traffic_morning", "traffic_midday", "traffic_evening",
        "avg_traffic", "traffic_peak_ratio",
    ],
    "Competition Pressure": [
        "comp_count_300", "comp_count_500", "comp_count_1k", "comp_gradient",
    ],
    "Transport Access": [
        "dist_transport", "dist_road", "road_type", "access_score",
    ],
    "Market Proximity": [
        "dist_market", "market_exposure",
    ],
    "Residential Density": [
        "pop_density",
    ],
}

# Below this magnitude, a factor's net effect is treated as neutral/mixed
RATING_THRESHOLD = 0.012


def _rating_from_shap(group_shap: float) -> str:
    if group_shap > RATING_THRESHOLD:
        return "favourable"
    if group_shap < -RATING_THRESHOLD:
        return "unfavourable"
    return "borderline"


def _pedestrian_detail(features, radius_meters, dominant):
    avg = features["avg_traffic"]
    return f"Estimated {avg:.0f} pedestrians per hour passing through this area."


def _competition_detail(features, radius_meters, dominant):
    radius_map = {300: "comp_count_300", 500: "comp_count_500", 1000: "comp_count_1k"}
    key = radius_map.get(int(radius_meters), "comp_count_300")
    display_radius = int(radius_meters) if int(radius_meters) in radius_map else 300
    count = int(features[key])
    return f"{count} personal care service{'s' if count != 1 else ''} observed within {display_radius}m."


def _transport_detail(features, radius_meters, dominant):
    """Transport Access covers dist_transport, dist_road, road_type, and
    access_score. The detail text describes whichever of these is actually
    driving the rating, so it never contradicts the badge."""
    if dominant == "dist_road":
        band = int(features["dist_road"])
        return f"This location is {DIST_BAND_LABELS[band]} the main road."
    if dominant == "road_type":
        return ("This location has tarmac road frontage." if features["road_type"] == 1
                else "This location has unpaved road frontage.")
    if dominant == "access_score":
        score = features["access_score"]
        level = "high" if score >= 6 else "moderate" if score >= 3 else "low"
        return f"Combined accessibility (transport, road, and market proximity) is {level}."
    band = int(features["dist_transport"])
    return f"Nearest transport stop is {DIST_BAND_LABELS[band]}."


def _market_detail(features, radius_meters, dominant):
    if dominant == "market_exposure":
        band = int(features["dist_market"])
        avg = features["avg_traffic"]
        return f"Nearest commercial anchor is {DIST_BAND_LABELS[band]}, with {avg:.0f} pedestrians/hour passing nearby."
    band = int(features["dist_market"])
    return f"Nearest market or commercial anchor is {DIST_BAND_LABELS[band]}."


def _density_detail(features, radius_meters, dominant):
    pd_val = features["pop_density"]
    return f"Population density in this area estimated at {pd_val:.0f} residents per cell."


DETAIL_BUILDERS = {
    "Pedestrian Activity":  _pedestrian_detail,
    "Competition Pressure": _competition_detail,
    "Transport Access":     _transport_detail,
    "Market Proximity":     _market_detail,
    "Residential Density":  _density_detail,
}

EXPLANATIONS = {
    "Pedestrian Activity": {
        "favourable":   "High foot traffic supports recurring walk-in demand, a strong signal for personal care services.",
        "borderline":   "Moderate foot traffic. Demand is present but may fluctuate by time of day.",
        "unfavourable": "Low pedestrian activity in this area limits daily walk-in customers.",
    },
    "Competition Pressure": {
        "favourable":   "A healthy cluster of similar businesses. Competition at this level often signals strong customer demand in the area.",
        "borderline":   "A moderate number of similar businesses nearby. The area is neither saturated nor underserved.",
        "unfavourable": "Competition here is either very high, meaning standing out will be difficult, or very low, which can signal limited demand.",
    },
    "Transport Access": {
        "favourable":   "Close to transport links and on accessible road infrastructure. This supports steady commuter-linked footfall.",
        "borderline":   "Moderate transport access. Customers can reach this location, but it is not directly on a major route.",
        "unfavourable": "Limited transport access. Reaching this location may require additional walking or transfers, which can reduce footfall.",
    },
    "Market Proximity": {
        "favourable":   "Close to a market or commercial hub. Businesses here benefit from existing foot traffic flowing through the area.",
        "borderline":   "Some distance from the nearest commercial anchor. Demand may rely more on the immediate neighbourhood than passing trade.",
        "unfavourable": "Far from markets or commercial hubs. This location will likely depend on building its own customer base over time.",
    },
    "Residential Density": {
        "favourable":   "A densely populated surrounding area. A strong base for the repeat weekly customers personal care services depend on.",
        "borderline":   "Moderate residential density. The catchment can support a business but may take time to build a loyal customer base.",
        "unfavourable": "A sparsely populated surrounding area. Recurring demand may be limited without strong transit-driven footfall.",
    },
}


def build_factor_breakdown(features: dict, shap_values: dict, radius_meters: int) -> list:
    """Builds the ordered list of factor dicts for the API response."""
    factors = []
    for factor_name, member_features in FACTOR_GROUPS.items():
        group_shap = sum(shap_values.get(f, 0.0) for f in member_features)
        rating = _rating_from_shap(group_shap)

        # The feature with the largest |SHAP| drives the detail text, so the
        # explanation never contradicts the badge.
        dominant = max(member_features, key=lambda f: abs(shap_values.get(f, 0.0)))

        detail = DETAIL_BUILDERS[factor_name](features, radius_meters, dominant)
        explanation = EXPLANATIONS[factor_name][rating]

        factors.append({
            "factor": factor_name,
            "rating": rating,
            "detail": detail,
            "explanation": explanation,
            "shap_contribution": round(group_shap, 4),
        })

    factors.sort(key=lambda f: abs(f["shap_contribution"]), reverse=True)
    return factors


def suitability_band(probability: float) -> str:
    if probability >= 0.65:
        return "FAVOURABLE"
    if probability >= 0.40:
        return "BORDERLINE"
    return "UNFAVOURABLE"
