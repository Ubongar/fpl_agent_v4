"""Dixon-Coles scoreline probability model.
lambda_home = home_attack * away_defence * home_advantage * league_avg
lambda_away = away_attack * home_defence * league_avg
Applies the low-score correlation (rho) adjustment from the original 1997 paper."""
import numpy as np
from scipy.stats import poisson

HOME_ADV = 1.15
LEAGUE_AVG_GOALS = 1.4
RHO = -0.05  # negative correlation adjustment for 0-0/1-0/0-1/1-1, fit via MLE in production

def tau(x, y, lam, mu, rho):
    if x == 0 and y == 0: return 1 - lam * mu * rho
    if x == 0 and y == 1: return 1 + lam * rho
    if x == 1 and y == 0: return 1 + mu * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def score_matrix(home_attack, away_defence, away_attack, home_defence, max_goals=6):
    lam = home_attack * away_defence * HOME_ADV * LEAGUE_AVG_GOALS
    mu = away_attack * home_defence * LEAGUE_AVG_GOALS
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            matrix[x, y] = poisson.pmf(x, lam) * poisson.pmf(y, mu) * tau(x, y, lam, mu, RHO)
    matrix /= matrix.sum()
    return matrix

def clean_sheet_prob(matrix, side="home"):
    return float(matrix[:, 0].sum()) if side == "home" else float(matrix[0, :].sum())

def expected_goals(matrix):
    xs, ys = np.indices(matrix.shape)
    return float((xs * matrix).sum()), float((ys * matrix).sum())
