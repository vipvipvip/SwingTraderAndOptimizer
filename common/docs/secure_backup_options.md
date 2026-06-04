# Secure DB Backup Credentials — Options

Options for obfuscating/securing credentials in `db-list.csv` used by `backup-mysql.sh`.

---

## 1. File Permissions (Minimum Baseline)

Credentials remain plaintext but are not world-readable:

```bash
chmod 600 db-list.csv
chown root:root db-list.csv
```

---

## 2. GPG Encryption

Encrypt the CSV once; the script decrypts it at runtime into memory (never touches disk).

**Encrypt:**
```bash
gpg --symmetric --cipher-algo AES256 db-list.csv
# Produces db-list.csv.gpg — delete the original afterwards
```

**Script reads via process substitution:**
```bash
while IFS=',' read -r DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME; do
    ...
done < <(gpg --quiet --decrypt db-list.csv.gpg)
```

Passphrase is stored in a gpg-agent or a secured keyfile. Good balance of simplicity and security.

---

## 3. Environment Variables

CSV holds no passwords — references env var names instead:

```
apptestingmysqlserver.mysql.database.azure.com,3306,AdminMySql,$QA_DB_PASSWORD,mailing
```

Actual values live in a root-owned env file sourced at the top of the script:

```bash
# /etc/backup-mysql.env  (chmod 600, chown root:root)
QA_DB_PASSWORD="your-password-here"
PROD_DB_PASSWORD="your-password-here"
```

```bash
# Top of backup-mysql.sh
source /etc/backup-mysql.env
```

Separates config from secrets cleanly.

---

## 4. Azure Key Vault (Recommended for Azure-hosted servers)

Store each password as a secret in Azure Key Vault and retrieve at runtime. No secrets on disk at all.

**Prerequisites:**
- VM must have a managed identity assigned
- Managed identity must have `Key Vault Secrets User` role on the vault

**Store a secret (once):**
```bash
az keyvault secret set --vault-name MyVault --name qa-db-password --value "your-password"
```

**Retrieve at runtime in script:**
```bash
DB_PASSWORD=$(az keyvault secret show --vault-name MyVault --name qa-db-password --query value -o tsv)
```

Benefits: zero secrets on disk, access is auditable via Azure Monitor.

---

## Recommendation

| Scenario | Recommended Option |
|---|---|
| Azure-hosted VM | Azure Key Vault + Managed Identity |
| Plain Linux server | GPG encryption |
| Quick/low-risk setup | File permissions + env file |
