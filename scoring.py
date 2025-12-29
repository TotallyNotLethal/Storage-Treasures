
def profit_score(a, velocity):
    score = 100
    score -= float(a["current_bid"]["amount"]) * 0.4
    score -= velocity * 5
    score += (100 - int(a["total_views"])) * 0.2
    score += (20 - int(a["total_bids"])) * 1.5
    return max(0, min(100, int(score)))
