vcl 4.1;

# Local stand-in for CloudFront. See docs/avatar-service-design.md, sections 9 and 13.5.
# NOTE: __ORIGIN_VERIFY_SECRET__ is replaced with the ORIGIN_VERIFY_SECRET env var when the container starts.

import std;

backend default {
    .host = "backend";
    .port = "8000";
}

# Only these sources may send BAN (invalidation) requests: private Docker/host network ranges.
acl ban_allowed {
    "localhost";
    "10.0.0.0"/8;
    "172.16.0.0"/12;
    "192.168.0.0"/16;
}

sub vcl_recv {
    # ---- Invalidation: BAN with a regex on the URL, e.g.  X-Ban-Pattern: ^/avatar/<email_hash> ----
    if (req.method == "BAN") {
        if (!client.ip ~ ban_allowed) {
            return (synth(403, "Forbidden"));
        }
        if (!req.http.X-Ban-Pattern) {
            return (synth(400, "Missing X-Ban-Pattern header"));
        }
        ban("obj.http.x-url ~ " + req.http.X-Ban-Pattern);
        return (synth(200, "Banned"));
    }

    # Only GET and HEAD are cacheable; everything else goes straight to the origin.
    if (req.method != "GET" && req.method != "HEAD") {
        return (pass);
    }

    # Only /avatar/* is cached (the JSON API does not go through the CDN anyway).
    if (req.url !~ "^/avatar/") {
        return (pass);
    }

    # ---- Cache key: path + only the "s" and "d" query parameters, in a stable order ----
    set req.url = regsuball(req.url, "([?&])(?!(s|d)=)[^&]*", "\1");
    set req.url = regsuball(req.url, "&+", "&");
    set req.url = regsub(req.url, "\?&", "?");
    set req.url = regsub(req.url, "[?&]+$", "");
    set req.url = std.querysort(req.url);

    # Avatars are public: never forward cookies or credentials.
    unset req.http.Cookie;
    unset req.http.Authorization;

    return (hash);
}

sub vcl_backend_fetch {
    # Proves to the origin that the request came through the CDN (design doc, section 9.5).
    set bereq.http.X-Origin-Verify = "__ORIGIN_VERIFY_SECRET__";
}

sub vcl_backend_response {
    # Remember the URL on the cached object so BAN can match it.
    set beresp.http.x-url = bereq.url;

    if (bereq.url ~ "^/avatar/") {
        unset beresp.http.Set-Cookie;
    }

    # Do not cache origin errors (including the 403 from the origin lock), except 404 which is a valid answer.
    if (beresp.status >= 400 && beresp.status != 404) {
        set beresp.uncacheable = true;
        set beresp.ttl = 5s;
        return (deliver);
    }

    # The CDN lifetime comes from "s-maxage" in the origin's Cache-Control header.
    # Browsers follow "max-age", which Varnish passes through unchanged.
}

sub vcl_deliver {
    unset resp.http.x-url;

    if (obj.hits > 0) {
        set resp.http.X-Cache = "HIT";
        set resp.http.X-Cache-Hits = obj.hits;
    } else {
        set resp.http.X-Cache = "MISS";
    }
}
