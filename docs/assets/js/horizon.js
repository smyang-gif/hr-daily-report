(function () {
  'use strict';

  var REPORT_ID_RE = /^\d{4}-\d{2}-\d{2}-(morning|evening)$/;
  var HEX_64_RE = /^[a-f0-9]{64}$/;
  var FEEDBACK_TIMEOUT_MS = 10000;

  /** Replace ⭐️ N/10 with a colored badge in h2, h3, and li elements. */
  function processScoreBadges() {
    var scoreRe = /⭐️\s*(\d+(?:\.\d+)?)\/10/;
    var targets = document.querySelectorAll('.main-content h2, .main-content h3, .main-content li');
    targets.forEach(function (el) {
      var match = el.innerHTML.match(scoreRe);
      if (!match) return;
      el.innerHTML = el.innerHTML.replace(scoreRe, scoreBadgeMarkup(match[1]));
    });
  }

  function scoreTier(score) {
    if (score >= 9) return 'high';
    if (score >= 7) return 'good';
    if (score >= 5) return 'mid';
    return 'low';
  }

  function scoreBadgeMarkup(scoreText) {
    return '<span class="score-badge" data-tier="' +
      scoreTier(parseFloat(scoreText)) + '">' + scoreText + '</span>';
  }

  function createScoreBadge(score) {
    var badge = document.createElement('span');
    badge.className = 'score-badge';
    badge.dataset.tier = scoreTier(score);
    badge.textContent = String(score);
    badge.setAttribute('aria-label', 'AI 선별 점수 ' + score + '점');
    return badge;
  }

  /** Add semantic classes to tag lines and source lines. */
  function markSemanticElements() {
    var paragraphs = document.querySelectorAll('.main-content p');
    paragraphs.forEach(function (paragraph) {
      var value = paragraph.textContent.trim();
      if (/^(Tags|标签|태그)\s*:/.test(value)) {
        paragraph.classList.add('tag-line');
        return;
      }
      if (/^(rss|reddit|github|hackernews|hn|telegram|google_news)\s*·/i.test(value)) {
        paragraph.classList.add('source-line');
      }
    });
  }

  /** Set up EN/中文 language toggle as a page-level control. */
  function setupLanguageToggle() {
    var toggle = document.createElement('div');
    toggle.className = 'lang-toggle';

    var btnEn = document.createElement('button');
    btnEn.textContent = 'EN';
    btnEn.type = 'button';

    var btnZh = document.createElement('button');
    btnZh.textContent = '中文';
    btnZh.type = 'button';

    toggle.appendChild(btnEn);
    toggle.appendChild(btnZh);
    document.body.insertBefore(toggle, document.body.firstChild);

    var saved = null;
    try { saved = localStorage.getItem('horizon-lang'); } catch (error) { /* noop */ }
    var currentLang = saved === 'en' ? 'en' : 'zh';

    function updateButtons(lang) {
      btnEn.classList.toggle('active', lang === 'en');
      btnZh.classList.toggle('active', lang !== 'en');
    }

    var zhSection = document.getElementById('lang-zh');
    var enSection = document.getElementById('lang-en');

    function showSection(lang) {
      if (!zhSection || !enSection) return;
      enSection.classList.toggle('hidden', lang !== 'en');
      zhSection.classList.toggle('hidden', lang === 'en');
    }

    function switchArticleLang(lang) {
      var path = window.location.pathname;
      var target = null;
      if (lang === 'en' && /-zh(?:\.html)?$/.test(path.replace(/\/$/, ''))) {
        target = path.replace(/-zh(\.html)?$/, '-en$1').replace(/-zh\/$/, '-en/');
      } else if (lang === 'zh' && /-en(?:\.html)?$/.test(path.replace(/\/$/, ''))) {
        target = path.replace(/-en(\.html)?$/, '-zh$1').replace(/-en\/$/, '-zh/');
      }
      if (target) window.location.href = target;
    }

    function setLang(lang) {
      currentLang = lang;
      updateButtons(lang);
      try { localStorage.setItem('horizon-lang', lang); } catch (error) { /* noop */ }
      if (zhSection && enSection) showSection(lang);
      else switchArticleLang(lang);
    }

    btnEn.addEventListener('click', function () { setLang('en'); });
    btnZh.addEventListener('click', function () { setLang('zh'); });
    updateButtons(currentLang);
    if (zhSection && enSection) showSection(currentLang);
  }

  function metaContent(name) {
    var meta = document.querySelector('meta[name="' + name + '"]');
    return meta ? meta.getAttribute('content') || '' : '';
  }

  function reportIdFromPage() {
    var explicit = metaContent('horizon-report-id');
    if (REPORT_ID_RE.test(explicit)) return explicit;

    var match = window.location.pathname.match(
      /\/(\d{4})\/(\d{2})\/(\d{2})\/(morning|evening)-summary-ko(?:\.html)?\/?$/
    );
    return match ? [match[1], match[2], match[3], match[4]].join('-') : null;
  }

  function safeHttpUrl(value) {
    if (typeof value !== 'string') return null;
    try {
      var parsed = new URL(value);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:'
        ? parsed.toString()
        : null;
    } catch (error) {
      return null;
    }
  }

  function newUuid() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
      var values = new Uint8Array(16);
      window.crypto.getRandomValues(values);
      values[6] = (values[6] & 15) | 64;
      values[8] = (values[8] & 63) | 128;
      var hex = Array.prototype.map.call(values, function (value) {
        return value.toString(16).padStart(2, '0');
      }).join('');
      return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' +
        hex.slice(16, 20) + '-' + hex.slice(20);
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (char) {
      var random = Math.floor(Math.random() * 16);
      return (char === 'x' ? random : (random & 3) | 8).toString(16);
    });
  }

  function visitorId() {
    var key = 'horizon-feedback-visitor-v1';
    try {
      var saved = localStorage.getItem(key);
      if (saved) return saved;
      var created = newUuid();
      localStorage.setItem(key, created);
      return created;
    } catch (error) {
      return newUuid();
    }
  }

  function reactionStorageKey(reportId, contentKey) {
    return 'horizon-feedback-v1:' + reportId + ':' + contentKey;
  }

  function storedReaction(reportId, contentKey) {
    try {
      var value = localStorage.getItem(reactionStorageKey(reportId, contentKey));
      return value === 'like' || value === 'dislike' ? value : null;
    } catch (error) {
      return null;
    }
  }

  function saveReaction(reportId, contentKey, reaction) {
    try {
      var key = reactionStorageKey(reportId, contentKey);
      if (reaction === 'clear') localStorage.removeItem(key);
      else localStorage.setItem(key, reaction);
    } catch (error) { /* The durable API remains the source of truth. */ }
  }

  function pendingStorageKey(reportId, contentKey) {
    return 'horizon-feedback-pending-v1:' + reportId + ':' + contentKey;
  }

  function pendingEvent(reportId, contentKey, manifestId, reaction) {
    var key = pendingStorageKey(reportId, contentKey);
    try {
      var saved = JSON.parse(localStorage.getItem(key) || 'null');
      if (saved && saved.manifest_id === manifestId && saved.reaction === reaction && saved.event_id) {
        return saved.event_id;
      }
      var eventId = newUuid();
      localStorage.setItem(key, JSON.stringify({
        event_id: eventId,
        manifest_id: manifestId,
        reaction: reaction
      }));
      return eventId;
    } catch (error) {
      return newUuid();
    }
  }

  function clearPendingEvent(reportId, contentKey) {
    try { localStorage.removeItem(pendingStorageKey(reportId, contentKey)); }
    catch (error) { /* noop */ }
  }

  function feedbackWidget(item, manifest, apiUrl, browserVisitorId) {
    var widget = document.createElement('div');
    widget.className = 'feedback-widget';
    widget.dataset.contentKey = item.content_key;

    var prompt = document.createElement('span');
    prompt.className = 'feedback-prompt';
    prompt.textContent = '이 콘텐츠는 어땠나요?';
    widget.appendChild(prompt);

    var info = document.createElement('a');
    info.className = 'feedback-info-link';
    info.href = metaContent('horizon-baseurl').replace(/\/$/, '') + '/feedback';
    info.textContent = '익명으로 기록됩니다 · 자세한 안내';
    info.setAttribute('aria-label', '익명 피드백 기록 안내');
    widget.appendChild(info);

    var controls = document.createElement('span');
    controls.className = 'feedback-controls';
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', item.title + ' 피드백');

    var like = document.createElement('button');
    like.type = 'button';
    like.className = 'feedback-button feedback-like';
    like.dataset.reaction = 'like';
    like.textContent = '👍 좋아요';

    var dislike = document.createElement('button');
    dislike.type = 'button';
    dislike.className = 'feedback-button feedback-dislike';
    dislike.dataset.reaction = 'dislike';
    dislike.textContent = '👎 별로예요';

    controls.appendChild(like);
    controls.appendChild(dislike);
    widget.appendChild(controls);

    var status = document.createElement('span');
    status.className = 'feedback-status';
    status.setAttribute('aria-live', 'polite');
    widget.appendChild(status);

    var current = storedReaction(manifest.report_id, item.content_key);

    function renderState() {
      like.setAttribute('aria-pressed', current === 'like' ? 'true' : 'false');
      dislike.setAttribute('aria-pressed', current === 'dislike' ? 'true' : 'false');
    }

    function setBusy(busy) {
      widget.setAttribute('aria-busy', busy ? 'true' : 'false');
      like.disabled = busy;
      dislike.disabled = busy;
    }

    async function submit(reaction) {
      var next = current === reaction ? 'clear' : reaction;
      if (!apiUrl) {
        status.textContent = '피드백 저장소가 아직 준비되지 않았습니다.';
        return;
      }
      setBusy(true);
      status.textContent = '저장 중…';
      var timeoutId = null;
      try {
        var controller = new AbortController();
        timeoutId = window.setTimeout(function () {
          controller.abort();
        }, FEEDBACK_TIMEOUT_MS);
        var eventId = pendingEvent(
          manifest.report_id,
          item.content_key,
          manifest.manifest_id,
          next
        );
        var response = await fetch(apiUrl, {
          method: 'POST',
          mode: 'cors',
          credentials: 'omit',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({
            event_id: eventId,
            report_id: manifest.report_id,
            manifest_id: manifest.manifest_id,
            content_key: item.content_key,
            visitor_id: browserVisitorId,
            reaction: next
          })
        });
        if (!response.ok) throw new Error('feedback request failed: ' + response.status);
        clearPendingEvent(manifest.report_id, item.content_key);
        current = next === 'clear' ? null : next;
        saveReaction(manifest.report_id, item.content_key, next);
        renderState();
        status.textContent = next === 'clear'
          ? '선택을 취소했습니다.'
          : '피드백을 기록했습니다.';
      } catch (error) {
        status.textContent = error && error.name === 'AbortError'
          ? '응답 시간이 초과되었습니다. 다시 시도해 주세요.'
          : '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      } finally {
        if (timeoutId !== null) window.clearTimeout(timeoutId);
        setBusy(false);
      }
    }

    like.addEventListener('click', function () { submit('like'); });
    dislike.addEventListener('click', function () { submit('dislike'); });
    renderState();
    return widget;
  }

  function displayDate(value) {
    if (!value) return '';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    try {
      return new Intl.DateTimeFormat('ko-KR', {
        month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit'
      }).format(date);
    } catch (error) {
      return value;
    }
  }

  function moreCard(item, manifest, apiUrl, browserVisitorId) {
    var url = safeHttpUrl(item.url);
    if (!url || typeof item.title !== 'string') return null;

    var card = document.createElement('article');
    card.className = 'reader-more-card';

    var header = document.createElement('div');
    header.className = 'reader-more-card-header';
    var title = document.createElement('h3');
    var link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = item.title;
    title.appendChild(link);
    header.appendChild(title);
    header.appendChild(createScoreBadge(Number(item.score)));
    card.appendChild(header);

    if (item.summary) {
      var summary = document.createElement('p');
      summary.className = 'reader-more-summary';
      summary.textContent = item.summary;
      card.appendChild(summary);
    }

    var metadataValues = [item.source_type, item.sub_source, item.author, displayDate(item.published_at)]
      .filter(function (value, index, all) {
        return typeof value === 'string' && value.trim() && all.indexOf(value) === index;
      });
    if (metadataValues.length) {
      var metadata = document.createElement('p');
      metadata.className = 'reader-more-meta';
      metadata.textContent = metadataValues.join(' · ');
      card.appendChild(metadata);
    }

    if (Array.isArray(item.tags) && item.tags.length) {
      var tags = document.createElement('div');
      tags.className = 'reader-more-tags';
      item.tags.slice(0, 8).forEach(function (value) {
        if (typeof value !== 'string' || !value.trim()) return;
        var tag = document.createElement('span');
        tag.textContent = '#' + value.replace(/^#/, '');
        tags.appendChild(tag);
      });
      card.appendChild(tags);
    }

    card.appendChild(feedbackWidget(item, manifest, apiUrl, browserVisitorId));
    return card;
  }

  function appendMoreSection(main, items, manifest, apiUrl, browserVisitorId) {
    if (!items.length) return 0;
    var details = document.createElement('details');
    details.className = 'reader-more';

    var summary = document.createElement('summary');
    summary.textContent = '더 보기 · ' + manifest.minimum_score + '점 이상 미선정 ' + items.length + '건';
    details.appendChild(summary);

    var intro = document.createElement('p');
    intro.className = 'reader-more-intro';
    intro.textContent = '오늘의 핵심 보고서에는 들지 않았지만 기준 점수 이상을 받은 콘텐츠입니다.';
    details.appendChild(intro);

    var list = document.createElement('div');
    list.className = 'reader-more-list';
    details.appendChild(list);
    main.appendChild(details);

    var rendered = false;
    function renderCards() {
      if (rendered) return;
      rendered = true;
      items.forEach(function (item) {
        var card = moreCard(item, manifest, apiUrl, browserVisitorId);
        if (card) list.appendChild(card);
      });
    }
    details.addEventListener('toggle', function () {
      if (details.open) renderCards();
    });
    if (details.open) renderCards();
    return items.length;
  }

  function attachSelectedWidgets(main, items, manifest, apiUrl, browserVisitorId) {
    var attached = 0;
    items.forEach(function (item) {
      if (typeof item.anchor_id !== 'string') return;
      var anchor = document.getElementById(item.anchor_id);
      if (!anchor) return;

      // Kramdown wraps a standalone HTML anchor in a paragraph. Walk up to
      // the direct child of .main-content so both wrapped and direct anchors work.
      var anchorBlock = anchor;
      while (anchorBlock.parentElement && anchorBlock.parentElement !== main) {
        anchorBlock = anchorBlock.parentElement;
      }
      var heading = anchorBlock.nextElementSibling;
      if (!heading || heading.tagName !== 'H3' || heading.dataset.feedbackReady === 'true') return;
      heading.dataset.feedbackReady = 'true';

      // Ask after the reader reaches the end of the item, immediately before
      // its divider (or the next item/section when no divider is present).
      var insertionPoint = heading;
      var cursor = heading.nextElementSibling;
      while (cursor) {
        var containsNextAnchor = cursor.querySelector && cursor.querySelector('a[id^="item-"]');
        if (cursor.tagName === 'HR' || cursor.tagName === 'H2' || containsNextAnchor) break;
        insertionPoint = cursor;
        cursor = cursor.nextElementSibling;
      }
      var widget = feedbackWidget(item, manifest, apiUrl, browserVisitorId);
      if (cursor) main.insertBefore(widget, cursor);
      else insertionPoint.insertAdjacentElement('afterend', widget);
      attached += 1;
    });
    return attached;
  }

  function validManifest(manifest, reportId) {
    return manifest &&
      manifest.schema_version === 1 &&
      manifest.report_id === reportId &&
      HEX_64_RE.test(manifest.manifest_id) &&
      Array.isArray(manifest.items);
  }

  async function setupReaderFeedback() {
    var reportId = reportIdFromPage();
    var main = document.querySelector('.main-content');
    if (!reportId || !main) return;

    var baseUrl = metaContent('horizon-baseurl').replace(/\/$/, '');
    var manifestUrl = baseUrl + '/data/reports/' + encodeURIComponent(reportId) + '.json';
    try {
      var response = await fetch(manifestUrl, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) return;
      var manifest = await response.json();
      if (!validManifest(manifest, reportId)) return;

      var apiUrl = safeHttpUrl(metaContent('horizon-feedback-api'));
      var browserVisitorId = visitorId();
      var selected = manifest.items.filter(function (item) {
        return item && item.surface === 'selected' && HEX_64_RE.test(item.content_key || '');
      });
      var more = manifest.items.filter(function (item) {
        return item && item.surface === 'more' && HEX_64_RE.test(item.content_key || '');
      });
      var selectedCount = attachSelectedWidgets(main, selected, manifest, apiUrl, browserVisitorId);
      var moreCount = appendMoreSection(main, more, manifest, apiUrl, browserVisitorId);

      if (selectedCount || moreCount) {
        var note = document.createElement('p');
        note.className = 'reader-feedback-note';
        note.textContent = '임의 브라우저 식별값은 서버에서 일방향 변환해 보관합니다. 이름·이메일·원본 식별값은 저장하지 않으며, IP 기반 남용 제한 정보는 2시간 뒤 만료되고 후속 요청 때 삭제됩니다.';
        main.appendChild(note);
      }
    } catch (error) {
      // A missing optional enhancement must never make the briefing unreadable.
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    processScoreBadges();
    markSemanticElements();
    setupLanguageToggle();
    setupReaderFeedback();
  });
})();
