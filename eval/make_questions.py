"""Builds eval/questions.jsonl. Gold labels are chosen from the file tree / titles / literal grep, never from the
search ranking, so the eval does not reward whatever the system already does.

origin=hand      written from real documentation tasks (gold pages picked by listing, then verified to exist)
origin=synthetic written from a seeded random chunk of the page (stratified by repo); questions paraphrase the chunk
Identifier questions: gold = every page in the corpus whose text literally contains the token.
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "current.db"
OUT = Path(__file__).with_name("questions.jsonl")
A = "azure-docs/articles/"
D = "azure-dev-docs/articles/"

Q = []   # (category, origin, question, gold sources, extras)


def add(cat, origin, q, gold, **kw):
    Q.append({"category": cat, "origin": origin, "question": q, "gold": gold, **kw})


# ---- conceptual / how-to (hand-written) -----------------------------------------------------------------------
H = "hand"
add("conceptual", H, "How can I limit access to my storage account to certain IP addresses or virtual networks?", [A + "storage/common/storage-network-security.md"])
add("conceptual", H, "What's the difference between the hot, cool, cold and archive blob tiers?", [A + "storage/blobs/access-tiers-overview.md"])
add("conceptual", H, "How does a load balancer decide whether a backend instance is healthy?", [A + "load-balancer/load-balancer-custom-probe-overview.md"])
add("conceptual", H, "How do I run an Azure Function on a schedule?", [A + "azure-functions/functions-bindings-timer.md"])
add("conceptual", H, "What is a dead-letter queue in Service Bus and when do messages end up there?", [A + "service-bus-messaging/service-bus-dead-letter-queues.md"])
add("conceptual", H, "How do I let my web app read secrets from Key Vault without putting them in app settings?", [A + "app-service/app-service-key-vault-references.md"])
add("conceptual", H, "What does the deny effect do in Azure Policy compared with audit?", [A + "governance/policy/concepts/effect-deny.md", A + "governance/policy/concepts/effect-audit.md", A + "governance/policy/concepts/effect-basics.md"])
add("conceptual", H, "How do I back up virtual machines in Azure and what gets backed up?", [A + "backup/backup-azure-vms-introduction.md"])
add("conceptual", H, "What pricing tiers and capacity limits do I get when I scale up an App Service plan?", [A + "app-service/manage-scale-up.md"])
add("conceptual", H, "How do I serve my own domain over HTTPS through Front Door?", [A + "frontdoor/standard-premium/how-to-configure-https-custom-domain.md"])
add("conceptual", H, "How do I connect my on-premises network to Azure with a site-to-site VPN?", [A + "vpn-gateway/tutorial-site-to-site-portal.md"])
add("conceptual", H, "How do I make a container app scale out automatically based on load?", [A + "container-apps/scale-app.md"])
add("conceptual", H, "How do I give someone read-only access to a resource group?", [A + "role-based-access-control/role-assignments-portal.md"])
add("conceptual", H, "How do I deploy a Bicep file to a resource group from the command line?", [A + "azure-resource-manager/bicep/deploy-cli.md"])

# ---- multi-page synthesis (hand-written) ----------------------------------------------------------------------
add("multi_page", H, "How do Front Door and Application Gateway differ for load balancing web traffic?", [A + "frontdoor/front-door-overview.md", A + "application-gateway/overview.md"])
add("multi_page", H, "What is the difference between private endpoints and service endpoints?", [A + "private-link/private-endpoint-overview.md", A + "virtual-network/virtual-network-service-endpoints-overview.md"])
add("multi_page", H, "Should I use a VPN gateway or ExpressRoute to link my datacenter to Azure?", [A + "vpn-gateway/vpn-gateway-about-vpngateways.md", A + "expressroute/expressroute-introduction.md"])
add("multi_page", H, "When would I pick Event Hubs rather than Service Bus?", [A + "event-hubs/event-hubs-about.md", A + "service-bus-messaging/service-bus-messaging-overview.md"])

# ---- variant-specific (hand-written; expected_variant must appear on the best gold hit) -------------------------
add("variant", H, "Change a storage account's replication type to zone-redundant using PowerShell", [A + "storage/common/redundancy-migration.md"], expected_variant="powershell")
add("variant", H, "Enable Microsoft Entra-only authentication for a Synapse workspace through the REST API", [A + "synapse-analytics/sql/authentication-azure-ad-only-authentication.md"], expected_variant="rest-api")
add("variant", H, "Delete a network interface with the Azure CLI", [A + "virtual-network/virtual-network-network-interface.md"], expected_variant="azure-cli")
add("variant", H, "Create a diagnostic setting for Blob storage using PowerShell", [A + "storage/blobs/monitor-blob-storage.md"], expected_variant="azure-powershell")
add("variant", H, "How do I mute a call on Android with the calling SDK?", [A + "communication-services/how-tos/calling-sdk/manage-calls.md"], expected_variant="platform-android")
add("variant", H, "Write a Durable Task orchestration in Go", [A + "durable-task/sdks/durable-task-overview.md"], expected_variant="go")

# ---- exact identifiers (gold computed corpus-wide by literal match) -------------------------------------------
for tok, q in [
    ("CannotRegisterModuleToModule", "What does the IoT Hub error CannotRegisterModuleToModule mean?"),
    ("rolling_refresh_token_lifetime_secs", "Which B2C token setting controls rolling_refresh_token_lifetime_secs?"),
    ("StringNotLike", "How do I use StringNotLike in an Azure role assignment condition?"),
    ("SkuPriceId", "What is the SkuPriceId column in the FOCUS cost and usage details file?"),
    ("MON_GET_CONNECTION", "Which Db2 table function does MON_GET_CONNECTION belong to in the Azure Monitor for SAP provider?"),
    ("UPDATED_AVAILABILITYZONE_NUMBER", "What is UPDATED_AVAILABILITYZONE_NUMBER used for when automating VMware migration?"),
    ("RemoveConnectionFromGroupAction", "RemoveConnectionFromGroupAction in Web PubSub Functions"),
    ("UploadSizeInBytes", "UploadSizeInBytes when moving a DevTest Labs lab"),
    ("Standard_M64s", "Standard_M64s custom disk configuration SAP deployment automation"),
]:
    add("identifier", H, q, None, token=tok)

# ---- synthetic (from seeded random chunks) --------------------------------------------------------------------
S = "synthetic"
add("conceptual", S, "After the carrier picks up my Data Box Disk, how do I know when Microsoft has received it?", [A + "databox/data-box-disk-deploy-upload-verify.md"])
add("conceptual", S, "Can an enterprise agreement service credit be paid out as cash?", [A + "cost-management-billing/manage/ea-pricing-overview.md"])
add("conceptual", S, "What happens to billing when I delete an Arize AI resource from the portal?", [A + "partner-solutions/arize-ai/manage.md"])
add("conceptual", S, "How do I attach an email communication resource to a network security perimeter profile with the CLI?", [A + "communication-services/quickstarts/network-security-perimeter.md"])
add("conceptual", S, "How does a Synapse reserved capacity discount apply if I run a DW1500c pool?", [A + "cost-management-billing/reservations/reservation-discount-azure-sql-dw.md"])
add("conceptual", S, "How can Managed Grafana query an InfluxDB server that lives inside my virtual network?", [A + "managed-grafana/how-to-connect-to-data-source-privately.md"])
add("conceptual", S, "Which triggers does the FTP connector have in a Standard logic app?", [A + "connectors/connectors-create-api-ftp.md"])
add("conceptual", S, "What REST call creates a backup policy for managed disks in a backup vault?", [A + "backup/backup-azure-dataprotection-use-rest-api-create-update-disk-policy.md"])
add("conceptual", S, "Can NetApp Files replicate a volume across zones and regions at the same time?", [A + "azure-netapp-files/replication.md"])
add("conceptual", S, "How do I deploy a locally built Spring Boot fat JAR to Azure Spring Apps?", [A + "spring-apps/basic-standard/how-to-launch-from-source.md"])
add("conceptual", S, "How do I route P1 and P2 incidents to a specific subagent in the SRE agent?", [A + "sre-agent/tutorial-incident-response.md"])
add("conceptual", S, "How do I stop other web apps from reusing my Hybrid Connection relay?", [A + "app-service/app-service-hybrid-connections.md"])
add("conceptual", S, "What metadata does a KEDA Azure Monitor scale rule need in Container Apps?", [A + "container-apps/java-metrics-scale-with-keda.md"])
add("conceptual", S, "How do I make an azd extension run as an MCP server?", [D + "azure-developer-cli/extensions/develop/extension-mcp-server.md"])
add("conceptual", S, "Which agent skill draws Mermaid architecture diagrams of a resource group?", [D + "azure-skills/skills/azure-resource-visualizer.md"])
add("conceptual", S, "How do I set up the Log Analytics workspace for monitoring a JavaScript app?", [D + "javascript/logging.md"])
add("conceptual", S, "How should I work out per-tenant costs when tenants share an AKS cluster?", ["architecture-center/docs/guide/multitenant/service/aks.md"])
add("conceptual", S, "Where do I find the cost optimization workbook once it's deployed?", ["finops-toolkit/src/workbooks/optimization/README.md"])
add("conceptual", S, "How does the FinOps toolkit tell me about idle resources?", ["finops-toolkit/docs/alerts.md"])

# ---- unanswerable from this corpus ----------------------------------------------------------------------------
for q in ["How does Azure Cosmos DB split data across physical partitions?",
          "How do I upgrade the Kubernetes version of an AKS cluster?",
          "How do I turn on soft delete for an Azure Key Vault?",
          "What is the availability SLA for a single Azure virtual machine with premium SSD?",
          "What is a good recipe for sourdough bread?",
          "How do I configure a Google Cloud Pub/Sub trigger for an Azure Function?"]:
    add("unanswerable", H, q, [], answerable=False)


def main() -> None:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    known = {f"{r}/{p}" for r, p in db.execute("SELECT repo, path FROM docs")}
    bad = 0
    for i, q in enumerate(Q, 1):
        q["id"] = f"q{i:03d}"
        q.setdefault("answerable", True)
        if q.get("token"):
            rows = db.execute("SELECT DISTINCT d.repo || '/' || d.path FROM chunks c JOIN docs d USING(doc_id) "
                              "WHERE instr(c.text, ?) > 0", (q["token"],)).fetchall()
            q["gold"] = sorted(r[0] for r in rows)
            print(f"{q['id']} {q['token']}: {len(q['gold'])} gold page(s)")
            if not q["gold"]:
                bad += 1
        for g in q["gold"]:
            if g not in known:
                print("MISSING GOLD", q["id"], g); bad += 1
    if bad:
        sys.exit(f"{bad} problems; not writing")
    OUT.write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in Q) + "\n")
    from collections import Counter
    print(len(Q), "questions", dict(Counter(q["category"] for q in Q)), dict(Counter(q["origin"] for q in Q)))


main()
