document.addEventListener('DOMContentLoaded', function () {
  var textarea = document.getElementById('sms-message');
  if (!textarea) return;

  var charCountEl = document.getElementById('sms-char-count');
  var segmentCountEl = document.getElementById('sms-segment-count');
  var totalCountEl = document.getElementById('sms-total-count');
  var selectAll = document.getElementById('select-all-drivers');
  var selectedCountEl = document.getElementById('selected-driver-count');
  var driverChecks = document.querySelectorAll('.driver-check');

  // GSM 03.38 basic character set -- messages made up only of these characters
  // (plus the extended set below, which each cost 2 chars) send as one 160-char
  // segment; anything else (emoji, most accented letters) forces UCS-2 encoding,
  // which drops the limit to 70 chars -- mirrors what Beem actually bills for.
  var GSM_BASIC = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
  var GSM_EXTENDED = "^{}\\[~]|€";

  function isGsm7(text) {
    for (var i = 0; i < text.length; i++) {
      if (GSM_BASIC.indexOf(text[i]) === -1 && GSM_EXTENDED.indexOf(text[i]) === -1) {
        return false;
      }
    }
    return true;
  }

  function gsmLength(text) {
    var len = 0;
    for (var i = 0; i < text.length; i++) {
      len += GSM_EXTENDED.indexOf(text[i]) !== -1 ? 2 : 1;
    }
    return len;
  }

  function selectedDriverCount() {
    var count = 0;
    driverChecks.forEach(function (cb) {
      if (cb.checked) count++;
    });
    return count;
  }

  function updateCounter() {
    var text = textarea.value;
    var gsm7 = isGsm7(text);
    var length = gsm7 ? gsmLength(text) : text.length;
    var singleLimit = gsm7 ? 160 : 70;
    var multiLimit = gsm7 ? 153 : 67;

    var segments = length === 0 ? 0 : length <= singleLimit ? 1 : Math.ceil(length / multiLimit);
    var limit = segments <= 1 ? singleLimit : segments * multiLimit;

    if (charCountEl) charCountEl.textContent = length + ' / ' + limit;
    if (segmentCountEl) segmentCountEl.textContent = segments;

    var selected = selectedDriverCount();
    if (selectedCountEl) selectedCountEl.textContent = selected;
    if (totalCountEl) totalCountEl.textContent = segments * selected;
  }

  textarea.addEventListener('input', updateCounter);

  driverChecks.forEach(function (cb) {
    cb.addEventListener('change', function () {
      if (selectAll) selectAll.checked = selectedDriverCount() === driverChecks.length;
      updateCounter();
    });
  });

  if (selectAll) {
    selectAll.addEventListener('change', function () {
      driverChecks.forEach(function (cb) {
        cb.checked = selectAll.checked;
      });
      updateCounter();
    });
  }

  updateCounter();
});
