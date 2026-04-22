(function () {
    document.addEventListener("DOMContentLoaded", function () {
        const COLLAPSIBLE_SCOPE = document.querySelector(".main-content");
        const PAGE_STATE_KEY = "collapsible-state:" + window.location.pathname;
        const SCROLL_STATE_KEY = "collapsible-scroll-restore";

        if (!COLLAPSIBLE_SCOPE) {
            return;
        }

        const containerSelectors = [
            ".card",
            ".home-panel",
            ".platform-panel"
        ];
        const headerSelectors = [
            ".card-header",
            ".home-panel-head",
            ".platform-panel-head"
        ];
        const excludedContainerSelectors = [
            "[data-collapse-exempt]",
            ".page-header",
            ".dashboard-page-header",
            ".messages-wrapper",
            ".alert",
            ".home-hero-panel",
            ".platform-hero",
            ".system-home-hero",
            ".system-home-hero-main",
            ".home-aside-card",
            ".home-stat-pill",
            ".platform-side-card",
            ".platform-stat-card",
            ".platform-feature-card",
            ".backup-summary-card",
            ".summary-card",
            ".metric-card",
            ".profile-modal-shell",
            ".profile-modal-section-card",
            ".modal-content",
            ".offcanvas",
            ".dropdown-menu",
            "details"
        ];
        const interactiveSelectors = [
            "a",
            "button",
            "input",
            "select",
            "textarea",
            "label",
            "summary",
            "[role='button']",
            "[data-modal-open]",
            "[data-modal-close]",
            "[data-dropdown-trigger]"
        ].join(", ");
        let collapseIdCounter = 0;
        let storedStates = {};

        try {
            storedStates = JSON.parse(sessionStorage.getItem(PAGE_STATE_KEY) || "{}") || {};
        } catch (error) {
            storedStates = {};
        }

        function saveStoredStates() {
            sessionStorage.setItem(PAGE_STATE_KEY, JSON.stringify(storedStates));
        }

        function matchesAnySelector(element, selectors) {
            return selectors.some(function (selector) {
                return element.matches(selector);
            });
        }

        function findDirectHeader(container) {
            return Array.from(container.children).find(function (child) {
                return matchesAnySelector(child, headerSelectors);
            }) || null;
        }

        function isExcludedContainer(container) {
            if (matchesAnySelector(container, excludedContainerSelectors)) {
                return true;
            }

            return Boolean(container.closest(".profile-modal-shell, .profile-modal-page, .profile-modal-body, details"));
        }

        function hasAncestorCandidate(container) {
            let current = container.parentElement;

            while (current && current !== COLLAPSIBLE_SCOPE) {
                if (matchesAnySelector(current, containerSelectors) && findDirectHeader(current)) {
                    return true;
                }
                current = current.parentElement;
            }

            return false;
        }

        function shouldSkipToggle(eventTarget, header) {
            if (!eventTarget || eventTarget === header) {
                return false;
            }

            const interactiveAncestor = eventTarget.closest(interactiveSelectors);
            return Boolean(interactiveAncestor && interactiveAncestor !== header);
        }

        function setExpandedState(container, header, content, isExpanded) {
            container.classList.toggle("is-expanded", isExpanded);
            container.classList.toggle("is-collapsed", !isExpanded);
            header.setAttribute("aria-expanded", isExpanded ? "true" : "false");
            content.setAttribute("aria-hidden", isExpanded ? "false" : "true");
            const stateKey = container.getAttribute("data-collapsible-key");
            if (stateKey) {
                storedStates[stateKey] = isExpanded ? "expanded" : "collapsed";
                saveStoredStates();
            }
            if ("inert" in content) {
                content.inert = !isExpanded;
            } else if (!isExpanded) {
                content.setAttribute("inert", "");
            } else {
                content.removeAttribute("inert");
            }
        }

        function buildCollapseKey(container, header, fallbackIndex) {
            if (container.dataset.collapseKey) {
                return container.dataset.collapseKey;
            }

            if (container.id) {
                return "id:" + container.id;
            }

            const headerText = (header.textContent || "")
                .trim()
                .toLowerCase()
                .replace(/\s+/g, "-")
                .replace(/[^a-z0-9\-_]/g, "")
                .slice(0, 60);

            if (headerText) {
                return "header:" + headerText + ":" + fallbackIndex;
            }

            return "index:" + fallbackIndex;
        }

        function restorePendingScrollTarget() {
            let pendingState = null;

            try {
                pendingState = JSON.parse(sessionStorage.getItem(SCROLL_STATE_KEY) || "null");
            } catch (error) {
                pendingState = null;
            }

            if (!pendingState || pendingState.path !== window.location.pathname) {
                return;
            }

            sessionStorage.removeItem(SCROLL_STATE_KEY);

            window.requestAnimationFrame(function () {
                const selector = pendingState.selector || "";
                const target = selector ? document.querySelector(selector) : null;
                if (target) {
                    target.scrollIntoView({ block: "start", behavior: "auto" });
                }
            });
        }

        function rememberInteractionTarget(targetElement) {
            const owningContainer = targetElement.closest("[data-collapsible-container]");
            if (!owningContainer) {
                return;
            }

            const containerId = owningContainer.id;
            const stateKey = owningContainer.getAttribute("data-collapsible-key");
            const selector = containerId ? ("#" + containerId) : (stateKey ? '[data-collapsible-key="' + stateKey + '"]' : "");

            if (!selector) {
                return;
            }

            sessionStorage.setItem(
                SCROLL_STATE_KEY,
                JSON.stringify({
                    path: window.location.pathname,
                    selector: selector
                })
            );
        }

        function expandForHashTarget() {
            const rawHash = window.location.hash;
            if (!rawHash) {
                return;
            }

            const targetId = rawHash.slice(1);
            if (!targetId) {
                return;
            }

            const target = document.getElementById(targetId);
            if (!target) {
                return;
            }

            const owningContainer = target.closest("[data-collapsible-container]");
            if (!owningContainer) {
                return;
            }

            const header = Array.from(owningContainer.children).find(function (child) {
                return child.classList.contains("collapse-toggle-header");
            });
            const content = Array.from(owningContainer.children).find(function (child) {
                return child.classList.contains("collapse-content");
            });

            if (header && content) {
                setExpandedState(owningContainer, header, content, true);
            }
        }

        Array.from(COLLAPSIBLE_SCOPE.querySelectorAll(containerSelectors.join(", "))).forEach(function (container) {
            if (isExcludedContainer(container) || hasAncestorCandidate(container)) {
                return;
            }

            const header = findDirectHeader(container);
            if (!header || header.hasAttribute("data-collapse-exempt")) {
                return;
            }

            const contentNodes = Array.from(container.children).filter(function (child) {
                return child !== header && !child.matches("script, style, template");
            });

            if (!contentNodes.length) {
                return;
            }

            collapseIdCounter += 1;

            const content = document.createElement("div");
            const contentInner = document.createElement("div");
            const contentId = container.id ? container.id + "-content" : "collapsible-section-" + collapseIdCounter;
            const indicator = document.createElement("span");
            const collapseKey = buildCollapseKey(container, header, collapseIdCounter);

            content.className = "collapse-content";
            content.id = contentId;
            content.setAttribute("aria-hidden", "true");

            contentInner.className = "collapse-content-inner";
            content.appendChild(contentInner);

            contentNodes.forEach(function (node) {
                contentInner.appendChild(node);
            });

            indicator.className = "collapse-indicator";
            indicator.setAttribute("aria-hidden", "true");
            header.appendChild(indicator);

            container.appendChild(content);
            container.classList.add("is-collapsible", "is-collapsed");
            container.setAttribute("data-collapsible-container", "true");
            container.setAttribute("data-collapsible-key", collapseKey);

            header.classList.add("collapse-toggle-header");
            header.setAttribute("role", "button");
            header.setAttribute("tabindex", "0");
            header.setAttribute("aria-expanded", "false");
            header.setAttribute("aria-controls", contentId);

            if ("inert" in content) {
                content.inert = true;
            } else {
                content.setAttribute("inert", "");
            }

            if (storedStates[collapseKey] === "expanded") {
                setExpandedState(container, header, content, true);
            }

            header.addEventListener("click", function (event) {
                if (shouldSkipToggle(event.target, header)) {
                    return;
                }

                setExpandedState(
                    container,
                    header,
                    content,
                    container.classList.contains("is-collapsed")
                );
            });

            header.addEventListener("keydown", function (event) {
                if (shouldSkipToggle(event.target, header)) {
                    return;
                }

                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setExpandedState(
                        container,
                        header,
                        content,
                        container.classList.contains("is-collapsed")
                    );
                }
            });
        });

        COLLAPSIBLE_SCOPE.addEventListener("click", function (event) {
            const interactiveTarget = event.target.closest("a, button");
            if (!interactiveTarget) {
                return;
            }
            rememberInteractionTarget(interactiveTarget);
        });

        COLLAPSIBLE_SCOPE.addEventListener("submit", function (event) {
            if (!event.target) {
                return;
            }
            rememberInteractionTarget(event.target);
        });

        expandForHashTarget();
        restorePendingScrollTarget();
        window.addEventListener("hashchange", expandForHashTarget);
    });
})();
