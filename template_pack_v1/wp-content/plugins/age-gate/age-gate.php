<?php
/**
 * Plugin Name: Age Gate
 * Description: Sitewide 18+ gate with remember=forever and on/off toggle.
 * Version: 0.1.0
 * Author: Template Pack v1
 */

if (!defined("ABSPATH")) { exit; }

define("AGEGATE_OPT_ENABLED", "agegate_enabled");
define("AGEGATE_COOKIE_BASENAME", "agegate_ok");

function agegate_is_enabled(): bool {
    $v = get_option(AGEGATE_OPT_ENABLED, "1");
    return ($v === "1" || $v === 1 || $v === true || $v === "true");
}

function agegate_cookie_name(): string {
    $blog_id = function_exists("get_current_blog_id") ? get_current_blog_id() : 1;
    return AGEGATE_COOKIE_BASENAME . "_" . intval($blog_id);
}

function agegate_register_settings() {
    register_setting("agegate_settings", AGEGATE_OPT_ENABLED);
}
add_action("admin_init", "agegate_register_settings");

function agegate_add_menu() {
    add_options_page("Age Gate", "Age Gate", "manage_options", "age-gate", "agegate_render_settings_page");
}
add_action("admin_menu", "agegate_add_menu");

function agegate_render_settings_page() {
    if (!current_user_can("manage_options")) { return; }
    $enabled = agegate_is_enabled();
    ?>
    <div class="wrap">
        <h1>Age Gate</h1>
        <form method="post" action="options.php">
            <?php settings_fields("agegate_settings"); ?>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row">Enable sitewide 18+ gate</th>
                    <td>
                        <input type="hidden" name="<?php echo esc_attr(AGEGATE_OPT_ENABLED); ?>" value="0" />
                        <label>
                            <input type="checkbox" name="<?php echo esc_attr(AGEGATE_OPT_ENABLED); ?>" value="1" <?php checked($enabled); ?> />
                            Enabled
                        </label>
                        <p class="description">If enabled: first visit shows 18+ gate. Remember = “forever” (very long cookie).</p>
                    </td>
                </tr>
            </table>
            <?php submit_button(); ?>
        </form>
    </div>
    <?php
}

function agegate_should_show_gate(): bool {
    if (!agegate_is_enabled()) return false;
    $cookie = agegate_cookie_name();
    return empty($_COOKIE[$cookie]);
}

function agegate_enqueue_assets() {
    if (!agegate_should_show_gate()) return;

    $css = "\n#agegate-overlay{position:fixed;inset:0;z-index:999999;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:16px;}\n" .
           "#agegate-card{max-width:520px;width:100%;background:#fff;border-radius:16px;padding:20px 18px;box-shadow:0 10px 30px rgba(0,0,0,.35);font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;}\n" .
           "#agegate-title{font-size:20px;line-height:1.2;margin:0 0 8px 0;}\n" .
           "#agegate-text{font-size:14px;line-height:1.45;margin:0 0 14px 0;color:#222;}\n" .
           "#agegate-actions{display:flex;gap:10px;flex-wrap:wrap;}\n" .
           ".agegate-btn{appearance:none;border:0;border-radius:12px;padding:12px 14px;font-size:14px;cursor:pointer}\n" .
           ".agegate-btn-primary{background:#111;color:#fff;}\n" .
           ".agegate-btn-ghost{background:#f2f2f2;color:#111;}\n" .
           "@media (max-width:480px){#agegate-card{border-radius:14px;padding:18px 14px;}#agegate-actions{flex-direction:column;} .agegate-btn{width:100%;}}\n";

    $js = "\n(function(){\n" .
          "  function setCookie(name,val,days){\n" .
          "    var d=new Date(); d.setTime(d.getTime()+days*24*60*60*1000);\n" .
          "    document.cookie = name+\"=\"+encodeURIComponent(val)+\"; expires=\"+d.toUTCString()+\"; path=/; SameSite=Lax\";\n" .
          "  }\n" .
          "  function closeGate(){\n" .
          "    var el=document.getElementById(\"agegate-overlay\");\n" .
          "    if(el){ el.parentNode.removeChild(el); }\n" .
          "    document.documentElement.style.overflow=\"\";\n" .
          "  }\n" .
          "  document.addEventListener(\"click\",function(e){\n" .
          "    var t=e.target; if(!t) return;\n" .
          "    if(t.id===\"agegate-yes\"){\n" .
          "      setCookie(window.AGEGATE_COOKIE_NAME,\"1\",3650);\n" .
          "      closeGate();\n" .
          "    }\n" .
          "    if(t.id===\"agegate-no\"){\n" .
          "      window.location.href=\"https://www.google.com/\";\n" .
          "    }\n" .
          "  }, true);\n" .
          "  document.documentElement.style.overflow=\"hidden\";\n" .
          "})();\n";

    wp_register_style("age-gate-inline", false);
    wp_enqueue_style("age-gate-inline");
    wp_add_inline_style("age-gate-inline", $css);

    wp_register_script("age-gate-inline", false);
    wp_enqueue_script("age-gate-inline");
    wp_add_inline_script("age-gate-inline", "window.AGEGATE_COOKIE_NAME=\"" . esc_js(agegate_cookie_name()) . "\";", "before");
    wp_add_inline_script("age-gate-inline", $js);
}
add_action("wp_enqueue_scripts", "agegate_enqueue_assets");

function agegate_render_gate_html() {
    if (!agegate_should_show_gate()) return;
    ?>
    <div id="agegate-overlay" role="dialog" aria-modal="true" aria-labelledby="agegate-title">
      <div id="agegate-card">
        <h2 id="agegate-title">18+</h2>
        <p id="agegate-text">Сайт содержит материалы для лиц старше 18 лет. Подтвердите, пожалуйста, что вам уже исполнилось 18.</p>
        <div id="agegate-actions">
          <button class="agegate-btn agegate-btn-primary" id="agegate-yes" type="button">Мне есть 18</button>
          <button class="agegate-btn agegate-btn-ghost" id="agegate-no" type="button">Мне нет 18</button>
        </div>
      </div>
    </div>
    <?php
}
add_action("wp_footer", "agegate_render_gate_html", 1);
