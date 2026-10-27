// AI梦境画画师 (com.fnm.huahuashi) 动态抓取: OkHttp/HTTP 请求 + RSA Cipher + URL
Java.perform(function () {
    console.log('[*] hook loaded');

    // 1. Apache HttpClient (DefaultHttpClient.execute) — app 主请求路径
    try {
        var HttpPost = Java.use('org.apache.http.client.methods.HttpPost');
        HttpPost.$init.overload('java.lang.String').implementation = function (uri) {
            console.log('[POST] ' + uri);
            return this.$init(uri);
        };
    } catch (e) { console.log('httppost: ' + e); }

    try {
        var DHC = Java.use('org.apache.http.impl.client.DefaultHttpClient');
        DHC.execute.overloads.forEach(function (ov) {
            ov.implementation = function () {
                var arg = arguments[0];
                try { console.log('[EXEC] ' + arg.toString().substring(0, 500)); } catch (e) {}
                var resp = ov.apply(this, arguments);
                try {
                    var code = resp.getStatusLine().getStatusCode();
                    console.log('[RESP ' + code + '] ' + arg.getURI());
                    if (code === 200) {
                        var entity = resp.getEntity();
                        if (entity) {
                            var br = Java.use('java.io.BufferedReader').$new(
                                Java.use('java.io.InputStreamReader').$new(entity.getContent()));
                            var line, sb = '';
                            while ((line = br.readLine()) !== null) sb += line;
                            console.log('[BODY] ' + sb.substring(0, 3000));
                            br.close();
                        }
                    }
                } catch (e) {}
                return resp;
            };
        });
    } catch (e) { console.log('dhc: ' + e); }

    // 2. RSA Cipher — 抓 bdtoken 解密
    try {
        var Cipher = Java.use('javax.crypto.Cipher');
        Cipher.doFinal.overload('[B').implementation = function (input) {
            var out = this.doFinal(input);
            try {
                if (this.getAlgorithm().indexOf('RSA') >= 0) {
                    console.log('[RSA] alg=' + this.getAlgorithm());
                    console.log('[RSA-in-b64] ' + Java.use('android.util.Base64').encodeToString(input, 2));
                    console.log('[RSA-out-b64] ' + Java.use('android.util.Base64').encodeToString(out, 2));
                }
            } catch (e) {}
            return out;
        };
    } catch (e) { console.log('cipher: ' + e); }

    // 3. URL/URLConnection 兜底
    try {
        var URL = Java.use('java.net.URL');
        URL.$init.overload('java.lang.String').implementation = function (s) {
            if (s.indexOf('http') === 0) console.log('[URL] ' + s);
            return this.$init(s);
        };
    } catch (e) {}
});
