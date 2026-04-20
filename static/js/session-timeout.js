(function () {
    function getCsrfToken() {
        const csrfField = document.querySelector("input[name='csrfmiddlewaretoken']");
        if (csrfField && csrfField.value) {
            return csrfField.value;
        }

        const match = document.cookie.match(/(?:^|;\\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function formatRemainingTime(totalSeconds) {
        const seconds = Math.max(0, Number(totalSeconds) || 0);
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const remainingSeconds = seconds % 60;

        if (hours > 0) {
            return [hours, minutes, remainingSeconds]
                .map(function (value, index) {
                    return index === 0 ? String(value) : String(value).padStart(2, "0");
                })
                .join(":");
        }

        return [minutes, remainingSeconds]
            .map(function (value) {
                return String(value).padStart(2, "0");
            })
            .join(":");
    }

    document.addEventListener("DOMContentLoaded", function () {
        const timer = document.querySelector("[data-session-timeout]");
        const remainingNode = document.querySelector("[data-session-remaining]");

        if (!timer || !remainingNode) {
            return;
        }

        const timeoutSeconds = Number(timer.dataset.timeoutSeconds || 0);
        const warningSeconds = Number(timer.dataset.warningSeconds || 0);
        const pingUrl = timer.dataset.pingUrl || "";
        const expireUrl = timer.dataset.expireUrl || "";
        const loginUrl = document.body.dataset.loginUrl || "/accounts/login/";
        const nextUrl = window.location.pathname + window.location.search;
        const csrfToken = getCsrfToken();
        const pingCooldownMs = 60000;
        const activityThrottleMs = 5000;

        let deadlineMs = Date.now() + (Number(timer.dataset.remainingSeconds || 0) * 1000);
        let lastPingMs = Date.now();
        let lastActivityMarkerMs = 0;
        let isExpiring = false;

        function getRemainingSeconds() {
            return Math.max(0, Math.ceil((deadlineMs - Date.now()) / 1000));
        }

        function updateTimerState() {
            const remainingSeconds = getRemainingSeconds();
            remainingNode.textContent = formatRemainingTime(remainingSeconds);
            timer.classList.toggle("is-warning", remainingSeconds > 0 && remainingSeconds <= warningSeconds);
            timer.classList.toggle("is-danger", remainingSeconds <= 60);
        }

        function redirectToLogin(targetUrl) {
            window.location.assign(targetUrl || loginUrl);
        }

        async function expireSession() {
            if (isExpiring) {
                return;
            }

            isExpiring = true;

            try {
                const response = await fetch(expireUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-CSRFToken": csrfToken,
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json"
                    },
                    body: "next=" + encodeURIComponent(nextUrl)
                });

                let payload = null;
                try {
                    payload = await response.json();
                } catch (error) {}

                redirectToLogin(payload && payload.login_url ? payload.login_url : loginUrl + "?session=expired");
            } catch (error) {
                redirectToLogin(loginUrl + "?session=expired");
            }
        }

        async function pingSession() {
            if (isExpiring || !pingUrl) {
                return;
            }

            const now = Date.now();
            if (now - lastPingMs < pingCooldownMs) {
                return;
            }

            lastPingMs = now;

            try {
                const response = await fetch(pingUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-CSRFToken": csrfToken,
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json"
                    },
                    body: "next=" + encodeURIComponent(nextUrl)
                });

                if (response.status === 401) {
                    let payload = null;
                    try {
                        payload = await response.json();
                    } catch (error) {}
                    redirectToLogin(payload && payload.login_url ? payload.login_url : loginUrl + "?session=expired");
                    return;
                }

                if (!response.ok) {
                    return;
                }

                const payload = await response.json();
                if (payload && typeof payload.remaining_seconds !== "undefined") {
                    deadlineMs = Date.now() + (Number(payload.remaining_seconds || timeoutSeconds) * 1000);
                    updateTimerState();
                }
            } catch (error) {}
        }

        function recordActivity() {
            const now = Date.now();
            if (now - lastActivityMarkerMs < activityThrottleMs) {
                return;
            }

            lastActivityMarkerMs = now;

            if (document.hidden) {
                return;
            }

            if (getRemainingSeconds() <= warningSeconds || now - lastPingMs >= pingCooldownMs) {
                pingSession();
            }
        }

        ["click", "keydown", "mousedown", "mousemove", "pointerdown", "scroll", "touchstart"].forEach(function (eventName) {
            document.addEventListener(eventName, recordActivity, { passive: true });
        });

        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) {
                if (getRemainingSeconds() <= 0) {
                    expireSession();
                    return;
                }
                pingSession();
            }
        });

        window.addEventListener("pageshow", function () {
            if (getRemainingSeconds() <= 0) {
                expireSession();
                return;
            }
            pingSession();
        });

        updateTimerState();

        window.setInterval(function () {
            updateTimerState();

            if (getRemainingSeconds() <= 0) {
                expireSession();
            }
        }, 1000);
    });
})();
