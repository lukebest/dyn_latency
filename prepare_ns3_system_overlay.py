#!/usr/bin/env python3
"""Apply the dyn_latency §4.3 packet-probe overlay to the pinned ns-3-ub tree.

The parent repository owns this overlay because the ns-3-ub submodule remote is
read-only in Cursor Cloud.  The transformations intentionally target the exact
submodule revision recorded by dyn_latency and fail loudly if that source
layout changes.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NS3 = ROOT / "ns-3-ub"
HEADER = NS3 / "src/unified-bus/model/ub-rg-experiment-app.h"
SOURCE = NS3 / "src/unified-bus/model/ub-rg-experiment-app.cc"
SCRATCH = NS3 / "scratch/ub_rg-packet-experiment.cc"
SENDER = NS3 / "src/unified-bus/model/protocol/ub-rg-sender-agent.cc"
SCHEDULER = NS3 / "src/unified-bus/model/protocol/ub-rg-scheduler.cc"
MARKER = "dyn_latency §4.3 system overlay"
PINNED_COMMIT = "742b5b1156c09347b8549bc0d2bb94415ce7ce50"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source match, found {count}")
    return text.replace(old, new, 1)


def replace_function(text: str, signature: str, next_signature: str, body: str) -> str:
    start = text.find(signature)
    end = text.find(next_signature, start)
    if start < 0 or end < 0:
        raise RuntimeError(f"cannot locate function block {signature!r}")
    return text[:start] + body.rstrip() + "\n\n" + text[end:]


BUILD_TOKENS = r"""
void
UbRgExperimentApp::BuildTokens()
{
    // dyn_latency §4.3 system overlay: Wide-EP and asymmetric AFD traffic.
    const bool afd = (m_mode == "afd_m2n" || m_mode == "afd_n2m");
    m_expertCount = afd ? m_nFfn : m_n;

    auto probabilities = [&](uint32_t count) {
        std::vector<double> probs(count);
        if (m_zipfS <= 0)
        {
            std::fill(probs.begin(), probs.end(), 1.0 / count);
        }
        else
        {
            double sum = 0;
            for (uint32_t i = 0; i < count; ++i)
            {
                probs[i] = 1.0 / std::pow(static_cast<double>(i + 1), m_zipfS);
                sum += probs[i];
            }
            for (double& p : probs)
            {
                p /= sum;
            }
        }
        return probs;
    };

    Ptr<UniformRandomVariable> uv = CreateObject<UniformRandomVariable>();
    uv->SetStream(m_seed);

    auto sampleTopK = [&](const std::vector<double>& probs,
                          int32_t excluded,
                          std::vector<uint32_t>& out) {
        out.clear();
        std::vector<char> used(probs.size(), 0);
        if (excluded >= 0 && static_cast<size_t>(excluded) < used.size())
        {
            used[excluded] = 1;
        }
        const uint32_t available =
            static_cast<uint32_t>(probs.size()) - (excluded >= 0 ? 1u : 0u);
        const uint32_t k = std::min(m_topk, available);
        for (uint32_t t = 0; t < k; ++t)
        {
            double remain = 0;
            for (uint32_t i = 0; i < probs.size(); ++i)
            {
                if (!used[i])
                {
                    remain += probs[i];
                }
            }
            if (remain <= 0)
            {
                break;
            }
            const double r = uv->GetValue(0.0, remain);
            double acc = 0;
            uint32_t chosen = static_cast<uint32_t>(probs.size() - 1);
            for (uint32_t i = 0; i < probs.size(); ++i)
            {
                if (used[i])
                {
                    continue;
                }
                acc += probs[i];
                if (r <= acc)
                {
                    chosen = i;
                    break;
                }
            }
            used[chosen] = 1;
            out.push_back(chosen);
        }
    };

    auto assignScheduler = [&](uint32_t src, uint32_t dst) -> std::pair<uint8_t, uint32_t> {
        if (m_scenario == 1)
        {
            uint32_t groupSize = std::max(1u, m_n / m_numPlanes);
            uint8_t plane =
                static_cast<uint8_t>(((src / groupSize) + (dst / groupSize)) % m_numPlanes);
            return {plane, dst};
        }
        uint32_t group = dst / 64;
        uint8_t plane = static_cast<uint8_t>(dst % m_numPlanes);
        uint8_t leafSched = static_cast<uint8_t>((8 * group + plane) % 256);
        return {leafSched, dst};
    };

    std::vector<uint32_t> attentionIds;
    std::vector<uint32_t> ffnIds;
    if (afd)
    {
        NS_ABORT_MSG_IF(m_nAttn == 0 || m_nFfn == 0,
                        "AFD requires positive --m-attn and --n-ffn");
        NS_ABORT_MSG_IF(m_nAttn + m_nFfn != m_n,
                        "AFD requires m-attn + n-ffn to equal active NPU count");
        if (m_placement == "plane_striped")
        {
            NS_ABORT_MSG_IF(m_n % m_numPlanes != 0 || m_nAttn % m_numPlanes != 0 ||
                                m_nFfn % m_numPlanes != 0,
                            "plane_striped requires total, M and N divisible by plane count");
            const uint32_t block = m_n / m_numPlanes;
            const uint32_t attnPerPlane = m_nAttn / m_numPlanes;
            const uint32_t ffnPerPlane = m_nFfn / m_numPlanes;
            for (uint32_t p = 0; p < m_numPlanes; ++p)
            {
                const uint32_t base = p * block;
                for (uint32_t i = 0; i < attnPerPlane; ++i)
                {
                    attentionIds.push_back(base + i);
                }
                for (uint32_t i = 0; i < ffnPerPlane; ++i)
                {
                    ffnIds.push_back(base + attnPerPlane + i);
                }
            }
        }
        else
        {
            NS_ABORT_MSG_IF(m_placement != "role_packed",
                            "placement must be role_packed or plane_striped");
            for (uint32_t i = 0; i < m_nAttn; ++i)
            {
                attentionIds.push_back(i);
            }
            for (uint32_t i = 0; i < m_nFfn; ++i)
            {
                ffnIds.push_back(m_nAttn + i);
            }
        }
    }
    else
    {
        attentionIds.resize(m_n);
        std::iota(attentionIds.begin(), attentionIds.end(), 0u);
        ffnIds = attentionIds;
    }

    const std::vector<double> probs = probabilities(afd ? m_nFfn : m_n);
    uint32_t tid = 1;
    std::vector<uint32_t> chosen;
    for (uint32_t src : attentionIds)
    {
        for (uint32_t b = 0; b < m_batch; ++b)
        {
            sampleTopK(probs, afd ? -1 : static_cast<int32_t>(src), chosen);
            for (uint32_t expert : chosen)
            {
                const uint32_t dst = ffnIds[expert];
                UbRgTokenDesc t;
                t.tokenId = tid++;
                t.src = src;
                t.dst = dst;
                t.expertRank = expert;
                t.bytes = GRAIN_BYTES;
                t.cursorId = 1;
                t.cursorValue = 1;
                auto [sid, hint] = assignScheduler(src, dst);
                t.schedulerId = sid;
                t.schedulerDstHint = hint;
                m_dispatchTokens.push_back(t);
                m_expertRank[t.tokenId] = expert;
            }
        }
    }

    // A standalone Combine/N2M phase gets a fresh task-id space.  The UB data
    // path has bounded wire sequence fields; carrying the unused Dispatch id
    // offset into a large standalone reverse phase can exceed that window.
    uint32_t combineTid = (m_mode == "roundtrip") ? tid : 1u;
    // Combine/N2M returns every routed expert result to its originating Attention NPU.
    for (const auto& t : m_dispatchTokens)
    {
        UbRgTokenDesc r = t;
        r.tokenId = combineTid++;
        r.src = t.dst;
        r.dst = t.src;
        auto [sid, hint] = assignScheduler(r.src, r.dst);
        r.schedulerId = sid;
        r.schedulerDstHint = hint;
        r.cursorId = 2;
        r.cursorValue = 1;
        m_combineTokens.push_back(r);
        m_expertRank[r.tokenId] = t.expertRank;
    }
}
"""


def patch_header(text: str) -> str:
    text = replace_once(
        text,
        "    void Configure(uint32_t scenario,\n"
        "                   const std::string& scheme,\n"
        "                   const std::string& mode,\n"
        "                   uint32_t batch,\n"
        "                   double zipfS,\n"
        "                   uint32_t topk,\n"
        "                   uint32_t epSize,\n"
        "                   uint32_t seed,\n"
        "                   const std::string& outDir);",
        "    // dyn_latency §4.3 system overlay\n"
        "    void Configure(uint32_t scenario,\n"
        "                   const std::string& scheme,\n"
        "                   const std::string& mode,\n"
        "                   uint32_t batch,\n"
        "                   double zipfS,\n"
        "                   uint32_t topk,\n"
        "                   uint32_t epSize,\n"
        "                   uint32_t seed,\n"
        "                   const std::string& outDir,\n"
        "                   uint32_t nAttn = 0,\n"
        "                   uint32_t nFfn = 0,\n"
        "                   const std::string& placement = \"role_packed\");",
        "Configure declaration",
    )
    return replace_once(
        text,
        "    uint32_t m_seed{1};\n"
        "    std::string m_outDir{\".\"};\n\n"
        "    uint32_t m_n{0};",
        "    uint32_t m_seed{1};\n"
        "    std::string m_outDir{\".\"};\n"
        "    uint32_t m_nAttn{0};\n"
        "    uint32_t m_nFfn{0};\n"
        "    uint32_t m_expertCount{0};\n"
        "    std::string m_placement{\"role_packed\"};\n\n"
        "    uint32_t m_n{0};",
        "member fields",
    )


def patch_source(text: str) -> str:
    text = replace_once(
        text,
        "                             uint32_t seed,\n"
        "                             const std::string& outDir)\n"
        "{\n"
        "    m_scenario = scenario;",
        "                             uint32_t seed,\n"
        "                             const std::string& outDir,\n"
        "                             uint32_t nAttn,\n"
        "                             uint32_t nFfn,\n"
        "                             const std::string& placement)\n"
        "{\n"
        "    // dyn_latency §4.3 system overlay\n"
        "    m_scenario = scenario;",
        "Configure definition",
    )
    text = replace_once(
        text,
        "    m_seed = seed;\n"
        "    m_outDir = outDir;\n"
        "}",
        "    m_seed = seed;\n"
        "    m_outDir = outDir;\n"
        "    m_nAttn = nAttn;\n"
        "    m_nFfn = nFfn;\n"
        "    m_placement = placement;\n"
        "}",
        "Configure assignments",
    )
    text = replace_once(
        text,
        "    m_n = (m_scenario == 1) ? 128u : 1024u;\n"
        "    if (m_epSize > 0 && m_epSize < m_n)\n"
        "    {\n"
        "        m_n = m_epSize;\n"
        "    }",
        "    m_n = (m_scenario == 1) ? 128u : 1024u;\n"
        "    if (m_epSize > 0 && m_epSize < m_n)\n"
        "    {\n"
        "        m_n = m_epSize;\n"
        "    }\n"
        "    if ((m_mode == \"afd_m2n\" || m_mode == \"afd_n2m\") && m_nAttn + m_nFfn > 0)\n"
        "    {\n"
        "        m_n = m_nAttn + m_nFfn;\n"
        "    }",
        "active NPU count",
    )
    text = replace_function(
        text,
        "void\nUbRgExperimentApp::BuildTokens()",
        "void\nUbRgExperimentApp::SetupSchedulersAndAgents()",
        BUILD_TOKENS,
    )
    text = replace_once(
        text,
        '    const bool doDispatch = (m_mode == "dispatch" || m_mode == "roundtrip");\n'
        '    const bool doCombineOnly = (m_mode == "combine");',
        '    const bool doDispatch = (m_mode == "dispatch" || m_mode == "roundtrip" ||\n'
        '                             m_mode == "afd_m2n");\n'
        '    const bool doCombineOnly = (m_mode == "combine" || m_mode == "afd_n2m");',
        "mode dispatch",
    )
    text = replace_once(
        text,
        "    if (rank < std::max(1u, m_n / 10))",
        "    if (rank < std::max(1u, m_expertCount / 10))",
        "hot threshold",
    )
    text = replace_once(
        text,
        "    if (rank >= m_n / 2)",
        "    if (rank >= m_expertCount / 2)",
        "cold threshold",
    )
    text = replace_once(
        text,
        "m_phaseCompleted % 200000 == 0",
        "m_phaseCompleted % 10000 == 0",
        "packet progress interval",
    )
    text = replace_once(
        text,
        '    if (m_mode == "dispatch")\n'
        "    {\n"
        "        konigUs = konigOf(m_dispatchTokens);\n"
        "    }\n"
        '    else if (m_mode == "combine")',
        '    if (m_mode == "dispatch" || m_mode == "afd_m2n")\n'
        "    {\n"
        "        konigUs = konigOf(m_dispatchTokens);\n"
        "    }\n"
        '    else if (m_mode == "combine" || m_mode == "afd_n2m")',
        "König mode",
    )
    text = replace_once(
        text,
        '    js << "  \\"engine\\": \\"packet\\",\\n";\n'
        '    js << "  \\"total_tokens\\": " << m_latCount << ",\\n";',
        '    js << "  \\"engine\\": \\"packet\\",\\n";\n'
        '    js << "  \\"profile\\": \\""\n'
        '       << ((m_mode == "afd_m2n" || m_mode == "afd_n2m") ? "afd" : "wide")\n'
        '       << "\\",\\n";\n'
        '    js << "  \\"traffic\\": \\"" << m_mode << "\\",\\n";\n'
        '    js << "  \\"m_attn\\": " << m_nAttn << ",\\n";\n'
        '    js << "  \\"n_ffn\\": " << m_nFfn << ",\\n";\n'
        '    js << "  \\"placement\\": \\"" << m_placement << "\\",\\n";\n'
        '    js << "  \\"total_tokens\\": " << m_latCount << ",\\n";',
        "summary extensions",
    )
    return text


def patch_scratch(text: str) -> str:
    text = replace_once(
        text,
        "    UbUtils::Get()->SetComponentsAttribute(casePath + \"/network_attribute.txt\");\n"
        "    if (scheme == \"packet_spray\" || scheme == \"ub_unscheduled\")",
        "    UbUtils::Get()->SetComponentsAttribute(casePath + \"/network_attribute.txt\");\n"
        "    // dyn_latency §4.3 system overlay: system CCT requires every routed\n"
        "    // token to complete; recover rare finite-buffer tail drops.\n"
        "    Config::SetDefault(\"ns3::UbTransportChannel::EnableRetrans\", BooleanValue(true));\n"
        "    if (scheme == \"packet_spray\" || scheme == \"ub_unscheduled\")",
        "packet reliability",
    )
    text = replace_once(
        text,
        '    std::string outDir = ".";\n'
        "    std::string casePath;\n"
        "    uint32_t mtpThreads = 0;",
        '    std::string outDir = ".";\n'
        "    std::string casePath;\n"
        "    uint32_t mtpThreads = 0;\n"
        "    uint32_t nAttn = 0;\n"
        "    uint32_t nFfn = 0;\n"
        '    std::string placement = "role_packed";',
        "scratch variables",
    )
    text = replace_once(
        text,
        '    cmd.AddValue("mode", "dispatch|combine|roundtrip", mode);',
        '    cmd.AddValue("mode", "dispatch|combine|roundtrip|afd_m2n|afd_n2m", mode);',
        "scratch mode help",
    )
    text = replace_once(
        text,
        '    cmd.AddValue("mtp-threads", "MTP threads (0=off)", mtpThreads);\n'
        "    cmd.Parse(argc, argv);",
        '    cmd.AddValue("mtp-threads", "MTP threads (0=off)", mtpThreads);\n'
        '    cmd.AddValue("m-attn", "AFD Attention NPU count", nAttn);\n'
        '    cmd.AddValue("n-ffn", "AFD FFN NPU count", nFfn);\n'
        '    cmd.AddValue("placement", "role_packed|plane_striped", placement);\n'
        "    cmd.Parse(argc, argv);",
        "scratch CLI",
    )
    return replace_once(
        text,
        "    exp->Configure(scenario, scheme, mode, batch, zipfS, topk, epSize, seed, outDir);",
        "    // dyn_latency §4.3 system overlay\n"
        "    exp->Configure(scenario,\n"
        "                   scheme,\n"
        "                   mode,\n"
        "                   batch,\n"
        "                   zipfS,\n"
        "                   topk,\n"
        "                   epSize,\n"
        "                   seed,\n"
        "                   outDir,\n"
        "                   nAttn,\n"
        "                   nFfn,\n"
        "                   placement);",
        "scratch Configure",
    )


def patch_sender(text: str) -> str:
    text = replace_once(
        text,
        "    bool haveCursor = false;\n"
        "    for (const auto& [tid, tok] : m_tokens)",
        "    bool haveCursor = false;\n"
        "    // dyn_latency §4.3 system overlay: pace REQ batches on VL1.  Sending\n"
        "    // thousands of control packets at the same simulation timestamp can\n"
        "    // overflow the control queue before CBFC reacts and permanently lose\n"
        "    // grants in high-skew AFD cases.\n"
        "    uint64_t requestSequence = 0;\n"
        "    for (const auto& [tid, tok] : m_tokens)",
        "REQ pacing state",
    )
    return replace_once(
        text,
        "            InjectToward(hintDst[sid], BuildRgPacket(hdr, 1), 1, sid % m_numPlanes);\n"
        "            off += n;",
        "            Ptr<Packet> request = BuildRgPacket(hdr, 1);\n"
        "            Simulator::Schedule(MicroSeconds(requestSequence++),\n"
        "                                &UbRgSenderAgent::InjectToward,\n"
        "                                this,\n"
        "                                hintDst[sid],\n"
        "                                request,\n"
        "                                1,\n"
        "                                sid % m_numPlanes);\n"
        "            off += n;",
        "REQ paced injection",
    )


def patch_scheduler(text: str) -> str:
    text = replace_once(
        text,
        "    const Time stale = MicroSeconds(500); // > control RTT; still unbound deadlock if DATA never returns",
        "    const Time stale = MicroSeconds(500); // > packet-probe control RTT; do not use 10µs",
        "stale grant timeout",
    )
    text = replace_once(
        text,
        "        InflightRec rec = it->second;\n"
        "        it = m_inflight.erase(it);\n"
        "        m_credit[rec.src] = std::min(m_creditWindow, m_credit[rec.src] + 1);\n"
        "        const uint64_t lkey = (static_cast<uint64_t>(rec.cursorId) << 16) | rec.cursorValue;\n"
        "        m_ledger[lkey].forwarded[rec.src] += 1;\n"
        "        CheckComplete(rec.cursorId, rec.cursorValue);",
        "        // dyn_latency §4.3 system overlay: a stale grant is not proof\n"
        "        // that DATA was forwarded. Requeue it so a lost GNT/DATA tail\n"
        "        // cannot silently disappear from system CCT.\n"
        "        const uint32_t tokenBufferId = static_cast<uint32_t>(it->first);\n"
        "        InflightRec rec = it->second;\n"
        "        it = m_inflight.erase(it);\n"
        "        m_credit[rec.src] = std::min(m_creditWindow, m_credit[rec.src] + 1);\n"
        "        PendingItem retry;\n"
        "        retry.srcNode = rec.src;\n"
        "        retry.tokenBufferId = tokenBufferId;\n"
        "        retry.grainIndex = 0;\n"
        "        retry.dstQueueId = 0;\n"
        "        retry.cursorId = rec.cursorId;\n"
        "        retry.cursorValue = rec.cursorValue;\n"
        "        m_pending[rec.egress][rec.src].push_back(retry);",
        "stale grant retry",
    )
    text = replace_once(
        text,
        "    m_active = active;\n"
        "    if (m_active && !m_roundEvent.IsPending())\n"
        "    {\n"
        "        m_roundEvent = Simulator::Schedule(m_tauG, &UbRgScheduler::ScheduleRound, this);\n"
        "    }",
        "    // dyn_latency §4.3 system overlay: an idle scheduler must not create\n"
        "    // one event every grain forever.  OnReqPacket wakes it when work arrives.\n"
        "    m_active = active;\n"
        "    if (!m_active && m_roundEvent.IsPending())\n"
        "    {\n"
        "        Simulator::Cancel(m_roundEvent);\n"
        "    }",
        "idle scheduler activation",
    )
    text = replace_once(
        text,
        "    CheckComplete(cursorId, cursorValue);\n"
        "}\n\n"
        "void\n"
        "UbRgScheduler::OnDataEgress",
        "    CheckComplete(cursorId, cursorValue);\n"
        "    if (!m_roundEvent.IsPending())\n"
        "    {\n"
        "        for (const auto& [egress, bySrc] : m_pending)\n"
        "        {\n"
        "            (void)egress;\n"
        "            if (!bySrc.empty())\n"
        "            {\n"
        "                m_roundEvent =\n"
        "                    Simulator::Schedule(m_tauG, &UbRgScheduler::ScheduleRound, this);\n"
        "                break;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        "void\n"
        "UbRgScheduler::OnDataEgress",
        "wake scheduler on request",
    )
    text = replace_once(
        text,
        "    ReclaimStaleInflight();\n"
        "    for (auto& [egress, bySrc] : m_pending)",
        "    ReclaimStaleInflight();\n"
        "    bool issuedGrant = false;\n"
        "    for (auto& [egress, bySrc] : m_pending)",
        "grant progress state",
    )
    text = replace_once(
        text,
        "        m_inflight[ikey] =\n"
        "            InflightRec{egress, chosenSrc, item.cursorId, item.cursorValue, Simulator::Now()};",
        "        m_inflight[ikey] =\n"
        "            InflightRec{egress, chosenSrc, item.cursorId, item.cursorValue, Simulator::Now()};\n"
        "        issuedGrant = true;",
        "grant progress update",
    )
    return replace_once(
        text,
        "    FlushGrants();\n"
        "    m_roundEvent = Simulator::Schedule(m_tauG, &UbRgScheduler::ScheduleRound, this);\n"
        "}",
        "    FlushGrants();\n"
        "    bool hasPending = false;\n"
        "    for (const auto& [egress, bySrc] : m_pending)\n"
        "    {\n"
        "        (void)egress;\n"
        "        if (!bySrc.empty())\n"
        "        {\n"
        "            hasPending = true;\n"
        "            break;\n"
        "        }\n"
        "    }\n"
        "    if (hasPending && issuedGrant)\n"
        "    {\n"
        "        m_roundEvent = Simulator::Schedule(m_tauG, &UbRgScheduler::ScheduleRound, this);\n"
        "    }\n"
        "    else if (!m_inflight.empty())\n"
        "    {\n"
        "        // No grants remain to issue. Jump to the earliest stale-grant\n"
        "        // deadline instead of spinning once per grain for hundreds of µs.\n"
        "        const Time now = Simulator::Now();\n"
        "        Time wait = MicroSeconds(10);\n"
        "        for (const auto& [key, rec] : m_inflight)\n"
        "        {\n"
        "            (void)key;\n"
        "            const Time deadline = rec.grantTime + MicroSeconds(10);\n"
        "            if (deadline > now)\n"
        "            {\n"
        "                wait = std::min(wait, deadline - now);\n"
        "            }\n"
        "            else\n"
        "            {\n"
        "                wait = NanoSeconds(1);\n"
        "                break;\n"
        "            }\n"
        "        }\n"
        "        m_roundEvent = Simulator::Schedule(wait, &UbRgScheduler::ScheduleRound, this);\n"
        "    }\n"
        "    else if (hasPending)\n"
        "    {\n"
        "        m_roundEvent = Simulator::Schedule(m_tauG, &UbRgScheduler::ScheduleRound, this);\n"
        "    }\n"
        "}",
        "idle scheduler reschedule",
    )


def baseline(path: Path) -> str:
    relative = path.relative_to(NS3).as_posix()
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative}"],
        cwd=NS3,
        text=True,
    )


def apply() -> None:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=NS3, text=True).strip()
    if actual != PINNED_COMMIT:
        raise RuntimeError(f"ns-3-ub commit {actual} is not supported; expected {PINNED_COMMIT}")
    transforms = (
        (HEADER, patch_header),
        (SOURCE, patch_source),
        (SCRATCH, patch_scratch),
        (SENDER, patch_sender),
        (SCHEDULER, patch_scheduler),
    )
    for path, transform in transforms:
        current = path.read_text(encoding="utf-8")
        if MARKER in current:
            continue
        expected = baseline(path)
        if current != expected:
            raise RuntimeError(f"refusing to overlay modified file: {path}")
        path.write_text(transform(current), encoding="utf-8")
        print(f"overlaid {path.relative_to(ROOT)}")


def restore() -> None:
    for path in (HEADER, SOURCE, SCRATCH, SENDER, SCHEDULER):
        current = path.read_text(encoding="utf-8")
        original = baseline(path)
        if current != original:
            path.write_text(original, encoding="utf-8")
            print(f"restored {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "restore"), default="apply", nargs="?")
    args = parser.parse_args()
    if args.action == "apply":
        apply()
    else:
        restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
