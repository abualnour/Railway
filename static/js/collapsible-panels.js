(function () {
    document.addEventListener("DOMContentLoaded", function () {
        const COLLAPSIBLE_SCOPE = document.querySelector(".main-content");

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
            if ("inert" in content) {
                content.inert = !isExpanded;
            } else if (!isExpanded) {
                content.setAttribute("inert", "");
            } else {
                content.removeAttribute("inert");
            }
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

        expandForHashTarget();
        window.addEventListener("hashchange", expandForHashTarget);
    });
})();
