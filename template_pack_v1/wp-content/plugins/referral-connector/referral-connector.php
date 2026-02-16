<?php
/**
 * Plugin Name: Referral Connector
 * Description: Captures referral code (/r/CODE) and sends WooCommerce order_paid events to Referral Service.
 * Version: 0.1.0
 * Author: Template Pack v1
 */

if (!defined("ABSPATH")) { exit; }

define("REFC_COOKIE_BASENAME", "ref_code");

function refc_cookie_name(): string {
    $blog_id = function_exists("get_current_blog_id") ? get_current_blog_id() : 1;
    return REFC_COOKIE_BASENAME . "_" . intval($blog_id);
}

function refc_attr_window_days(): int {
    $v = getenv("REF_ATTR_WINDOW_DAYS");
    $n = $v ? intval($v) : 60;
    return $n > 0 ? $n : 60;
}

function refc_set_cookie(string $name, string $value, int $days): void {
    $expire = time() + ($days * 24 * 60 * 60);
    $opts = [
        "expires"  => $expire,
        "path"     => "/",
        "secure"   => is_ssl(),
        "httponly" => true,
        "samesite" => "Lax",
    ];
    setcookie($name, $value, $opts);
}

function refc_capture_referral_link(): void {
    $uri = $_SERVER["REQUEST_URI"] ?? "";
    if (!$uri) return;
    if (preg_match("#^/r/([A-Za-z0-9_-]{3,64})/?$#", $uri, $m)) {
        $code = $m[1];
        refc_set_cookie(refc_cookie_name(), $code, refc_attr_window_days());
        wp_safe_redirect(home_url("/"), 302);
        exit;
    }
}
add_action("init", "refc_capture_referral_link", 1);

function refc_service_base_url(): string {
    $v = getenv("REFERRAL_BASE_URL");
    return $v ? rtrim($v, "/") : "http://referral-api:8080";
}

function refc_store_api_key(): string {
    $v = getenv("REFERRAL_STORE_API_KEY");
    return $v ? $v : "";
}

function refc_post_json(string $path, array $payload): void {
    $key = refc_store_api_key();
    if (!$key) return;
    $url = refc_service_base_url() . $path;
    $args = [
        "timeout" => 5,
        "headers" => [
            "Content-Type" => "application/json",
            "X-Store-Key"  => $key,
        ],
        "body" => wp_json_encode($payload),
    ];
    $resp = wp_remote_post($url, $args);
    if (is_wp_error($resp)) {
        error_log("refc: request failed: " . $resp->get_error_message());
        return;
    }
    $code = wp_remote_retrieve_response_code($resp);
    if ($code >= 400) {
        error_log("refc: service returned HTTP " . $code . " for " . $path);
    }
}

function refc_on_payment_complete($order_id): void {
    if (!function_exists("wc_get_order")) return;
    $order = wc_get_order($order_id);
    if (!$order) return;
    $cookie = refc_cookie_name();
    $ref_code = $_COOKIE[$cookie] ?? "";
    if (!$ref_code) return;
    $items = [];
    foreach ($order->get_items() as $item) {
        $items[] = [
            "product_id"   => $item->get_product_id(),
            "variation_id" => $item->get_variation_id(),
            "name"         => $item->get_name(),
            "qty"          => $item->get_quantity(),
            "total"        => (float) $item->get_total(),
        ];
    }
    $created = $order->get_date_created();
    $payload = [
        "event"    => "order_paid",
        "ref_code" => $ref_code,
        "order"    => [
            "id"         => (string) $order->get_id(),
            "number"     => (string) $order->get_order_number(),
            "total"      => (float) $order->get_total(),
            "currency"   => (string) $order->get_currency(),
            "email"      => (string) $order->get_billing_email(),
            "created_at" => $created ? $created->date("c") : "",
            "items"      => $items,
        ],
    ];
    refc_post_json("/events/order_paid", $payload);
}
add_action("woocommerce_payment_complete", "refc_on_payment_complete", 10, 1);
