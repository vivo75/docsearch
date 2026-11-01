# qset2 human review

Mark each item by replacing `[ ]` with `[x]` on the line that applies. Add a note after `note:` if useful.

## A. Questions (25)
For each: is it a realistic question, and does the gold page answer it?

### A1. n0033 (conceptual)
> I am trying to set up a secure migration environment and need to know how the appliance handles the sensitive credentials I enter during setup; are they transmitted to the cloud or kept on the local machine, and if local, how are they secured?

gold: [azure-docs/articles/migrate/best-practices-security.md](https://learn.microsoft.com/azure/migrate/best-practices-security)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A2. n0183 (howto)
> How can I upgrade the App Service plan tier of a Python web app deployed with azd by modifying its Bicep configuration?

gold: [azure-dev-docs/articles/python/quickstart-python-scale-bicep.md](https://learn.microsoft.com/azure/developer/python/quickstart-python-scale-bicep)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A3. n0419 (identifier)
> I am setting up a Jenkins controller on an Azure VM and saw `InstallAzureCli` in the setup instructions, but I'm unsure what that specific identifier refers to or how to execute it.

gold: `azure-cli/README.md`, `azure-cli/doc/install_troubleshooting.md`, [azure-compute-docs/articles/virtual-machines/linux/freebsd-intro-on-azure.md](https://learn.microsoft.com/azure/virtual-machines/linux/freebsd-intro-on-azure), [azure-dev-docs/articles/jenkins/deploy-from-github-to-aks.md](https://learn.microsoft.com/azure/developer/jenkins/deploy-from-github-to-aks)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A4. n0445 (multi_page)
> When troubleshooting a false positive on Azure Front Door versus Application Gateway, how do the available scope options for applying WAF rules or exclusions differ between the two services?

gold: [azure-docs/articles/web-application-firewall/afds/waf-front-door-tuning.md](https://learn.microsoft.com/azure/web-application-firewall/afds/waf-front-door-tuning), [azure-docs/articles/web-application-firewall/ag/application-gateway-waf-configuration.md](https://learn.microsoft.com/azure/web-application-firewall/ag/application-gateway-waf-configuration)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A5. n0462 (troubleshooting)
> Where should I submit an issue if I encounter a bug in the Azure CLI tools while managing my Web Application Firewall?

gold: [azure-docs/articles/web-application-firewall/support-help.md](https://learn.microsoft.com/azure/web-application-firewall/support-help)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A6. n0539 (unanswerable)
> How can I configure a systemd service to automatically restart if it crashes with a non-zero exit code?

gold: none (should be UNANSWERABLE from this corpus)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A7. n0625 (variant)
> How do I use the Azure CLI to create a new template spec from a local ARM template file and assign specific tags to it during the creation process?

gold: [azure-docs/articles/azure-resource-manager/templates/template-specs.md](https://learn.microsoft.com/azure/azure-resource-manager/templates/template-specs)
expected variant: `azure-cli`

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A8. n0030 (conceptual)
> When a single Azure Storage queue hits its throughput ceiling, what specific HTTP status codes does the service return, and what retry strategy is recommended to handle them?

gold: [azure-docs/articles/storage/queues/scalability-targets.md](https://learn.microsoft.com/azure/storage/queues/scalability-targets)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A9. n0274 (howto)
> What outbound domains must be allowed for dev tunnels?

gold: [azure-dev-docs/articles/dev-tunnels/security.md](https://learn.microsoft.com/azure/developer/dev-tunnels/security)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A10. n0362 (identifier)
> What does the `--map-by ppr:N:numa:pe=M` argument in an HPC-X mpirun command specify regarding process and thread distribution?

gold: [azure-compute-docs/articles/virtual-machines/sizes/high-performance-compute/hbv4-performance.md](https://learn.microsoft.com/azure/virtual-machines/sizes/high-performance-compute/hbv4-performance), [azure-compute-docs/articles/virtual-machines/sizes/high-performance-compute/hbv5-performance.md](https://learn.microsoft.com/azure/virtual-machines/sizes/high-performance-compute/hbv5-performance), [azure-compute-docs/articles/virtual-machines/sizes/high-performance-compute/hbv5-series-overview.md](https://learn.microsoft.com/azure/virtual-machines/sizes/high-performance-compute/hbv5-series-overview), [azure-compute-docs/articles/virtual-machines/sizes/high-performance-compute/hx-performance.md](https://learn.microsoft.com/azure/virtual-machines/sizes/high-performance-compute/hx-performance), [azure-compute-docs/articles/virtual-machines/sizes/high-performance-compute/setup-mpi.md](https://learn.microsoft.com/azure/virtual-machines/sizes/high-performance-compute/setup-mpi), [azure-docs/articles/high-performance-computing/performance-benchmarking/optimize-performance.md](https://learn.microsoft.com/azure/high-performance-computing/performance-benchmarking/optimize-performance)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A11. n0434 (multi_page)
> I am deploying an ASE with an ILB for a DoD workload connected via DISA CAP, but I am unsure which Azure Government region I should target for the deployment to ensure I am in the correct isolated infrastructure; which specific regions are available for Azure Government, and do they support availability zones?

gold: [azure-docs/articles/azure-government/documentation-government-ase-disa-cap.md](https://learn.microsoft.com/azure/azure-government/documentation-government-ase-disa-cap), [azure-docs/articles/azure-government/documentation-government-welcome.md](https://learn.microsoft.com/azure/azure-government/documentation-government-welcome)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A12. n0482 (troubleshooting)
> az dt route 400 bad request Cloud Shell

gold: [azure-docs/articles/digital-twins/troubleshoot-known-issues.md](https://learn.microsoft.com/azure/digital-twins/troubleshoot-known-issues)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A13. n0530 (unanswerable)
> I'm trying to enable the new 'Auto-Scaling Priority Queue' feature in my Application Gateway for Containers to handle bursty traffic, but I can't find the toggle in the portal; where is this setting located?

gold: none (should be UNANSWERABLE from this corpus)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A14. n0598 (variant)
> I am managing an App Service Environment v3 and need to permit the creation of private endpoint connections for my applications. How can I enable this specific setting directly within the Azure portal interface?

gold: [azure-docs/articles/app-service/environment/configure-network-settings.md](https://learn.microsoft.com/azure/app-service/environment/configure-network-settings)
expected variant: `azure-portal`

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A15. n0013 (conceptual)
> I am deploying edge applications that need to share state and avoid installing additional services like Redis, but I am worried about data loss during cluster maintenance; what happens to the stored key-value pairs if the Kubernetes cluster is stopped or restarted?

gold: [azure-docs/articles/iot-operations/develop-edge-apps/overview-state-store.md](https://learn.microsoft.com/azure/iot-operations/develop-edge-apps/overview-state-store)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A16. n0149 (howto)
> I need to run a specific application that relies on TCP/IP traffic over my InfiniBand interface rather than using standard MPI verbs, so how do I configure the VM to support this IP over InfiniBand communication?

gold: [azure-compute-docs/articles/virtual-machines/extensions/enable-infiniband.md](https://learn.microsoft.com/azure/virtual-machines/extensions/enable-infiniband)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A17. n0393 (identifier)
> How do I use the `DigitalTwinsModelData` class in a C# application to retrieve a list of all models currently uploaded to my Azure Digital Twins instance?

gold: [azure-docs/articles/digital-twins/how-to-manage-model.md](https://learn.microsoft.com/azure/digital-twins/how-to-manage-model), [azure-docs/articles/digital-twins/how-to-parse-models.md](https://learn.microsoft.com/azure/digital-twins/how-to-parse-models), [azure-docs/articles/digital-twins/tutorial-code.md](https://learn.microsoft.com/azure/digital-twins/tutorial-code)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A18. n0423 (multi_page)
> When migrating a Cloud Services (extended support) deployment to a supported Guest OS family, what specific .NET framework and Visual Studio versions are required to target Guest OS family 7, and what prerequisites regarding virtual network configuration must still be met in the .cscfg file?

gold: [azure-docs/articles/cloud-services-extended-support/deploy-prerequisite.md](https://learn.microsoft.com/azure/cloud-services-extended-support/deploy-prerequisite), [azure-docs/articles/cloud-services-extended-support/cloud-services-guestos-family-2-3-4-retirement.md](https://learn.microsoft.com/azure/cloud-services-extended-support/cloud-services-guestos-family-2-3-4-retirement)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A19. n0495 (troubleshooting)
> why savings plan utilization exceeds 100 percent

gold: [azure-docs/articles/cost-management-billing/savings-plan/troubleshoot-savings-plan-utilization.md](https://learn.microsoft.com/azure/cost-management-billing/savings-plan/troubleshoot-savings-plan-utilization)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A20. n0555 (unanswerable)
> How does the interaction between the default partition key and the indexing policy affect query performance when executing a cross-partition query on a large dataset in Azure Cosmos DB?

gold: none (should be UNANSWERABLE from this corpus)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A21. n0593 (variant)
> How do I authenticate my local PowerShell session to the Azure US Government cloud before starting the Azure MCP Server?

gold: [azure-dev-docs/articles/azure-mcp-server/how-to/connect-sovereign-clouds.md](https://learn.microsoft.com/azure/developer/azure-mcp-server/how-to/connect-sovereign-clouds)
expected variant: `powershell`

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A22. n0027 (conceptual)
> If I enable the preview for Microsoft Entra ID authentication for RDP connections, what specific feature becomes unavailable for concurrent use?

gold: [azure-docs/articles/bastion/whats-new.md](https://learn.microsoft.com/azure/bastion/whats-new)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A23. n0338 (howto)
> Add OpenAPI annotations to Spring Boot controller

gold: [azure-docs/articles/app-service/tutorial-ai-integrate-azure-ai-agent-java.md](https://learn.microsoft.com/azure/app-service/tutorial-ai-integrate-azure-ai-agent-java)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A24. n0417 (identifier)
> I see `MyFirstRunbook` in the code template, but I need to manage multiple virtual machines at once; how do I modify the runbook to accept a list of VM names and execute the actions in parallel?

gold: [azure-docs/articles/automation/learn/automation-tutorial-runbook-textual-python-3.md](https://learn.microsoft.com/azure/automation/learn/automation-tutorial-runbook-textual-python-3), [azure-docs/articles/automation/learn/automation-tutorial-runbook-textual.md](https://learn.microsoft.com/azure/automation/learn/automation-tutorial-runbook-textual)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

### A25. n0439 (multi_page)
> If I assign the User Access Administrator role to a team, can I restrict their ability to modify access permissions based on specific resource tags using Azure ABAC conditions?

gold: [azure-docs/articles/role-based-access-control/rbac-and-directory-admin-roles.md](https://learn.microsoft.com/azure/role-based-access-control/rbac-and-directory-admin-roles), [azure-docs/articles/role-based-access-control/conditions-overview.md](https://learn.microsoft.com/azure/role-based-access-control/conditions-overview)

- [ ] realistic and gold correct
- [ ] realistic but gold wrong/incomplete
- [ ] unrealistic / badly phrased
- note:

## B. Judge decisions (25)
The judge graded these pooled pages (2 = answers, 1 = partial, 0 = not useful). Do you agree?

### B1. n0307 → grade **1**
> When regenerating the Azure SDK for the Changes API, how do I instruct AutoRest to build the client specifically for the 2023-03-01-preview version?

page: `azure-rest-api-specs/specification/ai/data-plane/ContentUnderstanding/readme.md`
judge: _While the page provides a pattern for how to use the `--tag` flag with AutoRest for a different API version, it does not contain information regarding the 'Changes API' or the specific '2023-03-01-preview' version requested._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B2. n0145 → grade **1**
> Automate Java deployment pipelines on Azure

page: [azure-docs/articles/container-apps/migrate-java-github-copilot-app-modernization.md](https://learn.microsoft.com/azure/container-apps/migrate-java-github-copilot-app-modernization)
judge: _While the page describes an automated deployment process using GitHub Copilot for Java applications, it focuses on a specific migration tool rather than general CI/CD pipeline automation, and it only provides links to external documentation for setting up standard CI/CD pipelines._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B3. n0581 → grade **1**
> delete AKS resource group Azure CLI

page: [azure-aks-docs/articles/aks/delete-node-pool.md](https://learn.microsoft.com/azure/aks/delete-node-pool)
judge: _The user is asking how to delete an entire Resource Group containing AKS, but the page only provides instructions for deleting a specific node pool within an AKS cluster._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B4. n0205 → grade **2**
> I have deployed a Route Server but need to configure the BGP session on my network virtual appliance. How do I retrieve the specific autonomous system number and IP addresses required for the NVA to peer with the Route Server?

page: [azure-docs/articles/route-server/tutorial-protect-route-server-ddos.md](https://learn.microsoft.com/azure/route-server/tutorial-protect-route-server-ddos)
judge: _The page provides a direct, step-by-step guide on how to find the specific ASN and Peer IP addresses within the Azure portal to configure the NVA._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B5. n0302 → grade **2**
> I am defining a cluster template and need to reference a specific parameter within a larger string, but I keep getting the wrong value when I embed the variable directly in the text. How can I delimit the variable reference to ensure the system treats it as a distinct value rather than part of the surrounding text?

page: [azure-docs/articles/azure-resource-manager/templates/template-functions-deployment.md](https://learn.microsoft.com/azure/azure-resource-manager/templates/template-functions-deployment)
judge: _The page explains how to use the `variables()` function to retrieve values in ARM templates, which directly addresses the user's need to reference a parameter/variable within a template structure, though it doesn't explicitly use the word 'delimit', the syntax provided ([variables('name')]) is the solution to the problem described._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B6. n0462 → grade **2**
> Where should I submit an issue if I encounter a bug in the Azure CLI tools while managing my Web Application Firewall?

page: [azure-docs/articles/frontdoor/support-help.md](https://learn.microsoft.com/azure/frontdoor/support-help)
judge: _The page explicitly provides the GitHub issues URL for the Azure CLI, which is the specific tool mentioned in the question._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B7. n0332 → grade **0**
> How do I determine if an Event Hubs failure is temporary so my C++ application can automatically retry the operation?

page: [azure-docs/articles/durable-task/common/durable-task-error-handling.md](https://learn.microsoft.com/azure/durable-task/common/durable-task-error-handling)
judge: _The page discusses error handling for Azure Durable Functions in C# and PowerShell, which is completely unrelated to the user's request regarding Event Hubs and C++._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B8. n0465 → grade **2**
> Why can't I connect to my dedicated SQL pool from my corporate network?

page: [azure-docs/articles/synapse-analytics/sql-data-warehouse/sql-data-warehouse-overview-manage-security.md](https://learn.microsoft.com/azure/synapse-analytics/sql-data-warehouse/sql-data-warehouse-overview-manage-security)
judge: _The page provides direct troubleshooting steps for connection issues, specifically mentioning the need for server-level firewall rules to allow public IP addresses and ensuring that the local/corporate network allows outgoing communication on TCP port 1433._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B9. n0310 → grade **0**
> assign admin role to Kusto cluster principal

page: [azure-aks-docs/articles/aks/prepare-flex-node-host-identity.md](https://learn.microsoft.com/azure/aks/prepare-flex-node-host-identity)
judge: _The page discusses assigning roles to identities for AKS flex nodes, but it does not mention Kusto (Azure Data Explorer) or how to assign roles to a Kusto cluster principal._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B10. n0428 → grade **0**
> How do entitlement groups restrict search results?

page: [azure-docs/articles/microsoft-discovery/concept-project-rbac.md](https://learn.microsoft.com/azure/microsoft-discovery/concept-project-rbac)
judge: _The page discusses Azure RBAC and project-level access control, but it does not mention or explain 'entitlement groups' or how they specifically restrict search results._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B11. n0209 → grade **1**
> How can I use kubectl to determine if a DaemonSet has successfully deployed all its expected pods across the cluster?

page: [azure-aks-docs/articles/aks-hybrid-edge/windows-server/kubernetes-concepts.md](https://learn.microsoft.com/azure/aks-hybrid-edge/windows-server/kubernetes-concepts)
judge: _The page provides a conceptual definition of what a DaemonSet is, but it does not provide any kubectl commands or instructions on how to check the deployment status of pods._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B12. n0227 → grade **2**
> How should I structure the decomposition of an Azure workload into components to effectively balance cost with non-functional requirements like availability?

page: [architecture-center/docs/databases/idea/combine-relational-nosql-content.md](https://learn.microsoft.com/azure/architecture/databases/idea/combine-relational-nosql-content)
judge: _The page provides a specific architectural pattern (polyglot persistence) that demonstrates how to decompose a workload into relational and NoSQL components to optimize for both cost and performance/scalability, though it focuses more on data decomposition than general workload decomposition._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B13. n0581 → grade **2**
> delete AKS resource group Azure CLI

page: [azure-dev-docs/articles/ansible/aks-configure-cni-networking.md](https://learn.microsoft.com/azure/developer/ansible/aks-configure-cni-networking)
judge: _The page contains a specific section that provides the exact Azure CLI command requested to delete a resource group._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B14. n0008 → grade **0**
> Which specific log types does Azure Storage Actions support for monitoring, and what are the limitations regarding resource logs?

page: [azure-docs/articles/application-gateway/application-gateway-diagnostics.md](https://learn.microsoft.com/azure/application-gateway/application-gateway-diagnostics)
judge: _The page discusses Application Gateway logs, whereas the question specifically asks about 'Azure Storage Actions', making the content irrelevant to the user's specific query._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B15. n0175 → grade **0**
> What is the specific Azure CLI command required to retrieve code optimization recommendations from Application Insights via the MCP Server?

page: [azure-dev-docs/articles/azure-mcp-server/tools/azure-monitor.md](https://learn.microsoft.com/azure/developer/azure-mcp-server/tools/azure-monitor)
judge: _While the page discusses Azure MCP Server tools for Azure Monitor, it does not contain the specific command for retrieving code optimization recommendations from Application Insights._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B16. n0456 → grade **1**
> Why does my Virtual Machine Scale Set fail to scale out even when I apply heavy load to every individual instance, and what specific metric condition must be met to trigger a scale event?

page: [azure-compute-docs/articles/virtual-machine-scale-sets/virtual-machine-scale-sets-autoscale-portal.md](https://learn.microsoft.com/azure/virtual-machine-scale-sets/virtual-machine-scale-sets-autoscale-portal)
judge: _The page provides an example of how to set up a scale-out rule using an average metric, which implies that scaling is based on the average load across instances rather than individual instance load, but it does not explicitly state this as the reason for the user's failure._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B17. n0172 → grade **1**
> how to prevent cascading failures in distributed systems

page: [architecture-center/docs/patterns/compensating-transaction.md](https://learn.microsoft.com/azure/architecture/patterns/compensating-transaction)
judge: _The page discusses how to handle partial failures and maintain data consistency using compensating transactions, but it does not address 'cascading failures,' which is a specific phenomenon where one failure triggers a chain reaction of failures across a system._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B18. n0598 → grade **2**
> I am managing an App Service Environment v3 and need to permit the creation of private endpoint connections for my applications. How can I enable this specific setting directly within the Azure portal interface?

page: [azure-docs/articles/app-service/environment/networking.md](https://learn.microsoft.com/azure/app-service/environment/networking)
judge: _The page directly answers the question by specifying the exact setting name ('Allow new private endpoints') and the location within the Azure portal (the App Service Environment configuration pane)._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B19. n0399 → grade **0**
> I noticed the `--etcd-cafile` argument in my AKS CIS benchmark report; what does it do and how is it configured in Azure Kubernetes Service?

page: [azure-aks-docs/articles/aks/supported-kubernetes-versions.md](https://learn.microsoft.com/azure/aks/supported-kubernetes-versions)
judge: _The page discusses Kubernetes version support and upgrade policies, but it contains no information regarding the '--etcd-cafile' argument or how to configure etcd in AKS._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B20. n0259 → grade **1**
> What specific action must I take within the drill run details interface to conclude the execution and finalize the attestation?

page: [azure-docs/articles/resiliency/resiliency-whats-new.md](https://learn.microsoft.com/azure/resiliency/resiliency-whats-new)
judge: _The page mentions that drill tracking includes attestation, but it does not provide the specific action required within the interface to conclude the execution or finalize that attestation._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B21. n0292 → grade **2**
> How do I use PowerShell to list all Azure Resource Management private links within a specific resource group?

page: [azure-docs/articles/azure-resource-manager/management/manage-private-link-access-commands.md](https://learn.microsoft.com/azure/azure-resource-manager/management/manage-private-link-access-commands)
judge: _The page provides a PowerShell command (`Get-AzResourceManagementPrivateLink`) that takes a `-ResourceGroupName` parameter, which directly answers how to list/get a private link within a specific resource group._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B22. n0330 → grade **2**
> I need to implement a strategy for operating system updates across a large fleet of Windows virtual machines in Azure. What service should I use to centrally manage these updates and generate compliance reports?

page: [architecture-center/docs/virtual-machines/baseline-content.md](https://learn.microsoft.com/azure/architecture/virtual-machines/baseline-content)
judge: _The page explicitly identifies 'Azure Update Manager' as the service to manage OS updates for Windows and Linux virtual machines and describes it as a solution to manage and govern software updates._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B23. n0346 → grade **0**
> I am running a self-hosted gateway on Kubernetes and need to send its logs to a local syslog endpoint at /dev/log, but how do I configure the deployment to ensure the logs are actually written to the host file system?

page: [azure-docs/articles/api-management/api-management-howto-provision-self-hosted-gateway.md](https://learn.microsoft.com/azure/api-management/api-management-howto-provision-self-hosted-gateway)
judge: _The page only covers the initial provisioning of the gateway resource in the Azure portal and does not contain any information regarding Kubernetes deployment configurations, logging, or syslog integration._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B24. n0130 → grade **2**
> Check Node.js version in App Service

page: [azure-docs/articles/app-service/reference-app-settings.md](https://learn.microsoft.com/azure/app-service/reference-app-settings)
judge: _The page contains the specific environment variable `WEBSITE_NODE_DEFAULT_VERSION` and provides a link to documentation on how to show/configure the Node.js version, which directly addresses the user's intent._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:

### B25. n0416 → grade **0**
> What is the security implication if I create a broker authorization using `New-AzIoTOperationsServiceBrokerAuthorization` without specifying any rules?

page: [azure-compute-docs/articles/virtual-machines/linux/linux-remote-desktop-options.md](https://learn.microsoft.com/azure/virtual-machines/linux/linux-remote-desktop-options)
judge: _The page discusses Linux VDI architectures and general security best practices for remote desktops, but it contains no information regarding the specific PowerShell command `New-AzIoTOperationsServiceBrokerAuthorization` or IoT operations._

- [ ] agree
- [ ] should be 2
- [ ] should be 1
- [ ] should be 0
- note:
