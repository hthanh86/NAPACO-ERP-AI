/* Canonical purchasing formula: mm, g/cm3, kg/sheet. */
function filmCalculation(filmLength, filmWidth, cavity, qty, thickness, density, ng) {
    if (![filmLength, filmWidth, thickness, density].every(value => Number.isFinite(value) && value > 0) ||
        !Number.isSafeInteger(cavity) || cavity <= 0 || !Number.isSafeInteger(qty) || qty <= 0 ||
        !Number.isFinite(ng) || ng < 0 || ng > 100) return null;
    const sheets = Math.ceil(qty / cavity);
    const weight = thickness * (filmLength * filmWidth / 1000000) * density;
    const total = weight * sheets * (1 + ng / 100);
    if (!Number.isFinite(total) || total <= 0) return null;
    return { filmLength, filmWidth, sheets, weight, kg: Math.round(total / 10) * 10 };
  }
if (typeof module !== 'undefined') module.exports = filmCalculation;
if (typeof window !== 'undefined') window.filmCalculation = filmCalculation;
