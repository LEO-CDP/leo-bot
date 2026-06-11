<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>LEO BOT Login</title>
    <meta charset="utf-8"/>
    <link rel="icon" href="${url.resourcesPath}/img/favicon.ico" type="image/x-icon"/>
    <link rel="stylesheet" href="${url.resourcesPath}/css/login.css"/>
</head>

<body>
<div id="kc-header">
    <div id="kc-header-wrapper">
        <img src="${url.resourcesPath}/img/logo.png" alt="LEO BOT" class="leobot-logo">
        <h1>Welcome to LEO BOT</h1>
    </div>
</div>

<div id="kc-content">
    <div id="kc-form-wrapper">
        <#-- Render the default Keycloak login form -->
        <#include "login-form.ftl">
    </div>
</div>

<div id="kc-footer">
    <p class="footer-text">© 2025 LEO BOT — AI Assistant for LEO CDP</p>
</div>
</body>
</html>
