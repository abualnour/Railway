(function () {
    const STORAGE_KEY = "hr_theme_preference";
    const DEFAULT_THEME = "premium-dark";
    const ALLOWED_THEMES = ["premium-dark", "premium-light", "dark-accent", "sunrise"];
    const LEGACY_THEME_MAP = {
        "macos-glass": "sunrise"
    };
    const THEME_META_COLORS = {
        "premium-dark": "#091426",
        "premium-light": "#edf4ff",
        "dark-accent": "#12312d",
        "sunrise": "#eef3f8"
    };

    function normalizeTheme(theme) {
        const mappedTheme = LEGACY_THEME_MAP[theme] || theme;
        return ALLOWED_THEMES.includes(mappedTheme) ? mappedTheme : DEFAULT_THEME;
    }

    try {
        const rawStoredTheme = window.localStorage.getItem(STORAGE_KEY);
        const themeToApply = normalizeTheme(rawStoredTheme || document.documentElement.getAttribute("data-theme"));
        document.documentElement.setAttribute("data-theme", themeToApply);
        window.localStorage.setItem(STORAGE_KEY, themeToApply);

        const themeColorMeta = document.querySelector('meta[name="theme-color"]');
        if (themeColorMeta) {
            themeColorMeta.setAttribute("content", THEME_META_COLORS[themeToApply] || THEME_META_COLORS[DEFAULT_THEME]);
        }
    } catch (error) {
        document.documentElement.setAttribute("data-theme", DEFAULT_THEME);
    }
})();
