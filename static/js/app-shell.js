(function () {
    document.addEventListener("DOMContentLoaded", function () {
        const STORAGE_KEY_THEME = "hr_theme_preference";
        const DEFAULT_THEME = "premium-dark";
        const ALLOWED_THEMES = ["premium-dark", "premium-light", "dark-accent", "sunrise"];
        const LEGACY_THEME_MAP = {
            "macos-glass": "sunrise"
        };
        const BUTTONS = document.querySelectorAll("[data-theme-choice]");
        const themeColorMeta = document.querySelector('meta[name="theme-color"]');
        const metaColors = {
            "premium-dark": "#091426",
            "premium-light": "#edf4ff",
            "dark-accent": "#12312d",
            "sunrise": "#eef3f8"
        };

        function normalizeTheme(theme) {
            const mappedTheme = LEGACY_THEME_MAP[theme] || theme;
            return ALLOWED_THEMES.includes(mappedTheme) ? mappedTheme : DEFAULT_THEME;
        }

        function applyTheme(theme) {
            const normalizedTheme = normalizeTheme(theme);
            document.documentElement.setAttribute("data-theme", normalizedTheme);
            try {
                window.localStorage.setItem(STORAGE_KEY_THEME, normalizedTheme);
            } catch (error) {}
            if (themeColorMeta) {
                themeColorMeta.setAttribute("content", metaColors[normalizedTheme] || metaColors[DEFAULT_THEME]);
            }
            BUTTONS.forEach(function (button) {
                button.classList.toggle("is-active", button.dataset.themeChoice === normalizedTheme);
            });
        }

        let activeTheme = DEFAULT_THEME;
        try {
            activeTheme = normalizeTheme(
                window.localStorage.getItem(STORAGE_KEY_THEME) || document.documentElement.getAttribute("data-theme")
            );
        } catch (error) {
            activeTheme = DEFAULT_THEME;
        }
        applyTheme(activeTheme);
        BUTTONS.forEach(function (button) {
            button.addEventListener("click", function () {
                applyTheme(button.dataset.themeChoice);
            });
        });

        const navToggle = document.querySelector("[data-nav-toggle]");
        const navPanel = document.querySelector("[data-nav-panel]");
        const dropdowns = Array.from(document.querySelectorAll("[data-dropdown]"));

        if (navToggle && navPanel) {
            function closeNav() {
                navPanel.classList.remove("is-open");
                navToggle.setAttribute("aria-expanded", "false");
            }

            navToggle.addEventListener("click", function () {
                const isOpen = navPanel.classList.toggle("is-open");
                navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            });

            navPanel.querySelectorAll("a, button[type='submit']").forEach(function (item) {
                item.addEventListener("click", function () {
                    if (window.innerWidth <= 1024) {
                        closeNav();
                    }
                });
            });

            document.addEventListener("click", function (event) {
                if (window.innerWidth > 1024) {
                    return;
                }
                if (!navPanel.classList.contains("is-open")) {
                    return;
                }
                if (!navPanel.contains(event.target) && !navToggle.contains(event.target)) {
                    closeNav();
                }
            });

            window.addEventListener("resize", function () {
                if (window.innerWidth > 1024) {
                    navPanel.classList.remove("is-open");
                    navToggle.setAttribute("aria-expanded", "false");
                }
            });
        }

        function closeDropdown(dropdown) {
            const trigger = dropdown.querySelector("[data-dropdown-trigger]");
            dropdown.classList.remove("is-open");
            if (trigger) {
                trigger.setAttribute("aria-expanded", "false");
            }
        }

        function closeAllDropdowns(exceptDropdown) {
            dropdowns.forEach(function (dropdown) {
                if (exceptDropdown && dropdown === exceptDropdown) {
                    return;
                }
                closeDropdown(dropdown);
            });
        }

        dropdowns.forEach(function (dropdown) {
            const trigger = dropdown.querySelector("[data-dropdown-trigger]");
            if (!trigger) {
                return;
            }

            trigger.addEventListener("click", function (event) {
                event.preventDefault();
                event.stopPropagation();
                const shouldOpen = !dropdown.classList.contains("is-open");
                closeAllDropdowns(dropdown);
                if (shouldOpen) {
                    dropdown.classList.add("is-open");
                    trigger.setAttribute("aria-expanded", "true");
                } else {
                    closeDropdown(dropdown);
                }
            });
        });

        document.addEventListener("click", function (event) {
            const clickedInsideDropdown = dropdowns.some(function (dropdown) {
                return dropdown.contains(event.target);
            });
            if (!clickedInsideDropdown) {
                closeAllDropdowns();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeAllDropdowns();
            }
        });

        function wrapDateInputs(root) {
            const scope = root && root.querySelectorAll ? root : document;
            scope.querySelectorAll("input[type='date']").forEach(function (input) {
                if (input.parentElement && input.parentElement.classList.contains("date-input-wrap")) {
                    return;
                }

                const wrapper = document.createElement("span");
                wrapper.className = "date-input-wrap";
                input.parentNode.insertBefore(wrapper, input);
                wrapper.appendChild(input);
            });
        }

        function classifyActionButton(button) {
            if (!button || !button.classList || !button.classList.contains("btn")) {
                return;
            }

            if (
                button.closest(".topbar-panel") ||
                button.closest(".theme-toggle") ||
                button.hasAttribute("data-theme-choice")
            ) {
                return;
            }

            const label = (button.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
            if (!label) {
                return;
            }

            const actionClasses = [
                "btn-action-view",
                "btn-action-edit",
                "btn-action-delete",
                "btn-action-documents",
                "btn-action-approve",
                "btn-action-download",
                "btn-action-navigation",
                "btn-action-search",
                "btn-action-warning",
                "btn-action-neutral"
            ];

            button.classList.remove("btn-action-dot");
            actionClasses.forEach(function (className) {
                button.classList.remove(className);
            });

            let actionType = "";

            if (/(^|\\b)(delete|remove|reject|cancel|close|logout)(\\b|$)/.test(label)) {
                actionType = "delete";
            } else if (/(^|\\b)(document|documents|file|files|attachment|attachments)(\\b|$)/.test(label)) {
                actionType = "documents";
            } else if (/(^|\\b)(download|export|print)(\\b|$)/.test(label)) {
                actionType = "download";
            } else if (/(^|\\b)(approve|apply|submit|create|add|check in|check out|confirm|save)(\\b|$)/.test(label)) {
                actionType = "approve";
            } else if (/(^|\\b)(edit|update|change|manage|configure|settings|placement)(\\b|$)/.test(label)) {
                actionType = "edit";
            } else if (/(^|\\b)(view|open|details|overview|profile)(\\b|$)/.test(label)) {
                actionType = "view";
            } else if (/(^|\\b)(back|next|previous|reset|clear|return|directory|dashboard|home)(\\b|$)/.test(label)) {
                actionType = "navigation";
            } else if (/(^|\\b)(search|filter|find)(\\b|$)/.test(label)) {
                actionType = "search";
            } else if (/(^|\\b)(warning|risk|exception|correction)(\\b|$)/.test(label)) {
                actionType = "warning";
            } else {
                actionType = "neutral";
            }

            button.classList.add("btn-action-dot", "btn-action-" + actionType);
        }

        function decorateActionButtons(root) {
            const scope = root && root.querySelectorAll ? root : document;
            scope.querySelectorAll(".btn").forEach(function (button) {
                classifyActionButton(button);
            });
        }

        wrapDateInputs(document);
        decorateActionButtons(document);

        const dateInputObserver = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
                        return;
                    }

                    if (node.matches && node.matches("input[type='date']")) {
                        wrapDateInputs(node.parentElement || document);
                        decorateActionButtons(node.parentElement || document);
                        return;
                    }

                    wrapDateInputs(node);
                    decorateActionButtons(node);
                });
            });
        });

        dateInputObserver.observe(document.body, {
            childList: true,
            subtree: true
        });
    });
})();
