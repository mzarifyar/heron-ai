#!/bin/bash
set -e

# Azure Free Tier Setup ($200 credit for 30 days + always-free services)
# Prerequisites:
# 1. Create Azure account at https://azure.microsoft.com/free/
# 2. Run: az login
# 3. Set AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP

export AZURE_SUBSCRIPTION_ID=${AZURE_SUBSCRIPTION_ID:-"your-subscription-id"}
export AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP:-"heron-test-rg"}
export AZURE_LOCATION=${AZURE_LOCATION:-"eastus"}

echo "🚀 Provisioning Azure free tier resources for Heron discovery..."

# 1. Create resource group
echo "📍 Creating resource group..."
az group create \
  --name $AZURE_RESOURCE_GROUP \
  --location $AZURE_LOCATION \
  --subscription $AZURE_SUBSCRIPTION_ID
echo "   Resource Group: $AZURE_RESOURCE_GROUP"

# 2. Create B1s VM (free tier eligible)
echo "📍 Creating B1s Virtual Machine..."
az vm create \
  --resource-group $AZURE_RESOURCE_GROUP \
  --name heron-test-web-server \
  --image UbuntuLTS \
  --size Standard_B1s \
  --public-ip-sku Standard \
  --subscription $AZURE_SUBSCRIPTION_ID
echo "   VM: heron-test-web-server"

# 3. Create Azure SQL Database (B_Gen5_1 - free tier eligible first 12 months)
echo "📍 Creating Azure SQL Server and Database..."
az sql server create \
  --resource-group $AZURE_RESOURCE_GROUP \
  --name heron-test-sql-server \
  --location $AZURE_LOCATION \
  --admin-user sqladmin \
  --admin-password "HeronisFree2024!@" \
  --subscription $AZURE_SUBSCRIPTION_ID

az sql db create \
  --resource-group $AZURE_RESOURCE_GROUP \
  --server heron-test-sql-server \
  --name heron-test-db \
  --edition Free \
  --subscription $AZURE_SUBSCRIPTION_ID
echo "   SQL Database: heron-test-db"

# 4. Create Storage Account (5GB free)
echo "📍 Creating Storage Account..."
STORAGE_ACCOUNT="herontestsa$(date +%s | tail -c 6)"
az storage account create \
  --resource-group $AZURE_RESOURCE_GROUP \
  --name $STORAGE_ACCOUNT \
  --location $AZURE_LOCATION \
  --sku Standard_LRS \
  --subscription $AZURE_SUBSCRIPTION_ID
echo "   Storage Account: $STORAGE_ACCOUNT"

echo ""
echo "✅ Azure free tier resources created!"
echo ""
echo "Resources created:"
echo "  VM: heron-test-web-server (B1s - free first 12 months)"
echo "  SQL Database: heron-test-db (Free tier - 32 MB storage)"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo ""
echo "To use with Heron, add to .env:"
echo "  AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID"
echo "  AZURE_RESOURCE_GROUP=$AZURE_RESOURCE_GROUP"
