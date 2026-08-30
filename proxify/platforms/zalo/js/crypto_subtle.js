(function(){
    let g = typeof window !== 'undefined' ? window : self;
    if (g.__zalo_crypto_hooked) return;
    g.__zalo_crypto_hooked = true;

    if (g.crypto && g.crypto.subtle) {
        const _orig = g.crypto.subtle.decrypt;
        g.crypto.subtle.decrypt = async function() {
            let res = await _orig.apply(this, arguments);
            try {
                let buf = res;
                // Zalo compresses decrypted payloads with deflate-raw or deflate
                for (const algo of ['deflate-raw', 'deflate']) {
                    try {
                        const ds = new DecompressionStream(algo);
                        const w = ds.writable.getWriter();
                        w.write(buf); w.close();
                        buf = await new Response(ds.readable).arrayBuffer();
                        break;
                    } catch(_) {}
                }
                let text = "";
                try { text = new TextDecoder().decode(buf); } catch(e) {}
                
                // Check active group
                let currentGroupId = null;
                try {
                    if (typeof window !== 'undefined') {
                        if (window.__zalo_groupRuntime && window.__zalo_groupRuntime.currentGroupId) {
                            currentGroupId = String(window.__zalo_groupRuntime.currentGroupId).replace(/^g/, '');
                        } else {
                            let match = window.location.href.match(/g(\d+)/);
                            if (match) currentGroupId = match[1];
                        }
                    }
                } catch(e) {}

                if (currentGroupId && !text.includes(currentGroupId)) {
                    return res; // Ignore background traffic for other groups
                }

                // Only capture member/group data, skip chat messages
                const memberKeywords = ['"memberIds"', '"memberList"', '"memberProfiles"', '"topMember"', '"totalMember"'];
                if (memberKeywords.some(k => text.includes(k))) {
                    fetch('https://chat.zalo.me/api/capture_dump', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/octet-stream'},
                        body: buf
                    }).catch(function(){});
                }
            } catch(_) {}
            return res;
        };
    }
})();