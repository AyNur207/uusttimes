# Reusable university styles

Copy this **entire `university` directory** into your new project's public/static
assets. It contains the visual styles extracted from Campus Helper, including
your adaptations. It is not a verified copy of UUST's official design system.
The existing app still uses its original stylesheets; this is a portable kit for
new markup, rather than a replacement that you can drop into the old templates.

Open `preview.html` in a browser to see all modules together. The preview works
without Flask, Bootstrap, a database, or an internet connection. With no downloaded
font it uses your system font.

## What to import

| File | Purpose | Extracted from |
| --- | --- | --- |
| `core.css` | Entry point: imports the next three foundation files | Shared foundation |
| `tokens.css` | Colours, spacing, typography, radii, motion, shadows | All original stylesheets |
| `base.css` | Scoped typography, layout helpers, focus and reduced-motion rules | `style.css`, main/maps/tests |
| `components.css` | Header, cards, buttons, panels, badges, notices, useful-link lists | Main/maps/login/register/profile/news |
| `forms.css` | Shared login/registration form and field styling | `style_login.css`, `style_register.css` |
| `maps.css` | Image/map cards | `style_maps.css` |
| `profile.css` | Profile container, avatar and responsive layout | `style_profile.css` |
| `quiz.css` | Answers, progress, slides and results | `style_tests.css` |
| `news.css` | Feed layout, filters and article cards | `style_announcements.css` |

Every page needs `core.css`. Add only the optional modules that its elements use:

```html
<link rel="stylesheet" href="/assets/university/core.css">
<!-- Optional, for a page containing forms: -->
<link rel="stylesheet" href="/assets/university/forms.css">
<!-- Your project's overrides come last: -->
<link rel="stylesheet" href="/assets/site.css">

<body class="uni-theme">
  <main class="uni-container uni-section">
    <h1>University portal</h1>
    <p class="uni-lead">News, services and student life.</p>
    <a class="uni-button" href="/news">Read news</a>
  </main>
</body>
```

The `/assets/` URLs are examples; use your new project's actual static path.
In this Flask project, the core URL would be:

```html
<link rel="stylesheet"
      href="{{ url_for('static', filename='css/university/core.css') }}">
```

`core.css` imports its neighbours using relative URLs. Keep those files together.
Alternatively, link `tokens.css`, `base.css`, and `components.css` directly in
that order **instead of** linking `core.css`. This avoids CSS `@import` if your
build system prefers explicit links. No build step is required.

## Fonts and scope

The original templates load **Golos Text** separately. To use it here too, put
this before the CSS links (internet access required):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700&display=swap">
```

For offline use, provide your own licensed font files with `@font-face`, or keep
the system-font fallback. Logos and map images are supplied by your application;
the styles do not embed university assets or third-party fonts.

Put `uni-theme` on `body` for a whole site or on a wrapper for just part of a
page. Shared element rules are scoped to that wrapper. Component classes use the
`uni-` prefix and variables use `--uni-`, so they don't redefine Bootstrap's
`.card`, `.btn`, `.form-control`, `.progress`, or `.navbar`.

Do not combine the old global styles with this kit on a new page: rules such as
`div { padding: 30px 0 }` can still affect it. The kit deliberately removes that
rule and its later `div { padding: 0; margin: 0 }` counter-rule. Use `uni-stack`,
`uni-row`, `uni-grid`, and `uni-section` for spacing instead.

## Common components

Feature cards keep the purple/yellow design; plain cards stay neutral. They no
longer compete for a single `.card` selector:

```html
<div class="uni-grid">
  <a class="uni-card-link" href="/maps">
    <article class="uni-card uni-card--feature">
      <h2 class="uni-card__title">Campus maps</h2>
      <p class="uni-card__description">Find your building.</p>
    </article>
  </a>
  <article class="uni-card">
    <h2 class="uni-card__title">Student services</h2>
    <p>Neutral card content.</p>
    <footer class="uni-card__footer">
      <a class="uni-button uni-button--outline" href="/services">Explore</a>
    </footer>
  </article>
</div>
```

Buttons: `uni-button`, plus `--accent`, `--secondary`, `--outline`, or `--block`.
Use a real `disabled` attribute for disabled buttons. `aria-disabled` is only a
visual/semantic state here; application code must prevent activation on links.

Forms use `uni-form-card` (500px maximum), or add `uni-form-card--wide` (700px).
Use `uni-stack` on the form and `uni-field` around each label/control pair.

```html
<form class="uni-form-card uni-stack" method="post">
  <div class="uni-field">
    <label class="uni-label" for="email">Email</label>
    <input class="uni-control" id="email" name="email" type="email"
           autocomplete="email" required>
  </div>
  <button class="uni-button" type="submit">Continue</button>
</form>
```

Use `uni-field-help` for hints, `uni-field-error` for errors, and associate them
with the input using `aria-describedby`. Mark invalid controls with
`aria-invalid="true"`. Login and registration now share the same controls and
button rules.

## Optional module markup

Full examples of every module are in `preview.html`. Useful class mappings:

| Original element | Portable equivalent |
| --- | --- |
| `.navbar`, `.navbar_logo` | `.uni-navbar`, `.uni-navbar__logo` |
| `.card` on home/topics | `.uni-card.uni-card--feature` |
| `.card` on tests/results | `.uni-card` or `.uni-result` |
| `.login-card`, `.register-card` | `.uni-form-card`, add `.uni-form-card--wide` for registration |
| `.login-btn`, `.register-btn` | `.uni-button.uni-button--block` |
| `.form-label`, `.form-control` | `.uni-label`, `.uni-control` |
| `.map-card`, `.map-image`, `.map-card-body` | `.uni-map`, `.uni-map__image`, `.uni-map__body` |
| `.profile-card`, `.profile-image` | `.uni-profile`, `.uni-profile__image` |
| `.info-item`, `.links-card` | `.uni-info`, `.uni-panel` with `.uni-link-list` |
| `.answer`, `.letter` | `.uni-answer`, `.uni-answer__letter` |
| `.slide.active` | `.uni-quiz-slide.is-active` |
| `.progress`, `.progress-bar` | `.uni-progress`, `.uni-progress__bar` |
| `.btn-yellow` | `.uni-button.uni-button--quiz` (requires `quiz.css`) |
| `.post-card`, `.post-meta` | `.uni-post`, `.uni-post__meta` |
| `.filter-button` | `.uni-filter` |
| `.category-badge`, `.demo-badge` | `.uni-badge` with `--event` or `--muted` as appropriate |

The repeated quiz animation/answer rules were consolidated. Radios remain
focusable using `uni-visually-hidden`, instead of `display: none`. Native
checked states style quiz answers; keyboard focus and reduced motion are
supported. Selection highlighting uses `:has()` in modern browsers.

CSS does not implement authentication, map zoom dialogs, news fetching,
filtering, or quiz progression. Your code must update `hidden`, `is-active`,
`aria-pressed`, and progress-bar width as appropriate. Hide inactive quiz slides
with the `hidden` attribute; `is-active` only adds an entrance animation. The
preview includes a small news-filter demonstration, but is not a quiz engine.

## Customising the look

Override tokens in your stylesheet loaded **after** the kit:

```css
:root {
  --uni-primary: #4d19cc;
  --uni-heading: #2a1468;
  --uni-accent: #efbb3e;
  --uni-content-width: 1200px;
}
```

`--uni-quiz-accent` preserves the brighter yellow used in the old tests; the
general accent preserves the original homepage gold. Keep them separate if you
want those variations. Profile/news layouts and some spacing were normalised
for reuse and small screens, rather than copied pixel-for-pixel.
