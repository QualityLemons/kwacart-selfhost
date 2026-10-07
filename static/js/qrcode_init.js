/* ── Guest QR code — lazy generation ── */
/* Generates the guest-join QR code on demand when the details element is opened.
   The guest URL is read from data-guest-url on the #guest-qr-details element.
   Depends on qrcode.min.js being loaded before this script. */
(function () {

    var details = document.getElementById('guest-qr-details');
    if (!details) return;

    var generated = false;
    var guestUrl  = details.dataset.guestUrl;

    details.addEventListener('toggle', function () {
        if (this.open && !generated) {
            new QRCode(document.getElementById('guest-qrcode'), {
                text:       guestUrl,
                width:      200,
                height:     200,
                colorDark:  '#0f172a',
                colorLight: '#ffffff',
            });
            generated = true;
            details.querySelector('summary').textContent = '\u25be Hide guest QR code';
        } else if (!this.open) {
            details.querySelector('summary').innerHTML = '&#9654; Show guest QR code';
        }
    });

}());
