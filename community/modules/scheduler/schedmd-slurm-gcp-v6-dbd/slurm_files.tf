# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# BUCKET

locals {
  synt_suffix       = substr(md5("${var.project_id}${var.deployment_name}"), 0, 5)
  synth_bucket_name = "${local.slurm_cluster_name}${local.synt_suffix}"

  bucket_name = var.create_bucket ? module.bucket[0].name : var.bucket_name
}

module "bucket" {
  source  = "terraform-google-modules/cloud-storage/google"
  version = "~> 5.0"

  count = var.create_bucket ? 1 : 0

  location   = var.region
  names      = [local.synth_bucket_name]
  prefix     = "slurmdbd"
  project_id = var.project_id

  force_destroy = {
    (local.synth_bucket_name) = true
  }

  labels = merge(local.labels, {
    slurm_cluster_name = local.slurm_cluster_name
  })
}


resource "google_storage_bucket_iam_binding" "viewers" {
  bucket  = local.bucket_name
  role    = "roles/storage.objectViewer"
  members = toset(["serviceAccount:${module.slurm_dbd_template.service_account.email}"])
}

resource "google_storage_bucket_iam_binding" "legacy_readers" {
  bucket  = local.bucket_name
  role    = "roles/storage.legacyBucketReader"
  members = toset(["serviceAccount:${module.slurm_dbd_template.service_account.email}"])
}

locals {
  daos_ns = [
    for ns in var.network_storage :
    ns if ns.fs_type == "daos"
  ]

  daos_client_install_runners = [
    for ns in local.daos_ns :
    ns.client_install_runner if ns.client_install_runner != null
  ]

  daos_mount_runners = [
    for ns in local.daos_ns :
    ns.mount_runner if ns.mount_runner != null
  ]

  daos_network_storage_runners = concat(
    local.daos_client_install_runners,
    local.daos_mount_runners,
  )

  daos_install_mount_script = {
    filename = "ghpc_daos_mount.sh"
    content  = length(local.daos_ns) > 0 ? module.daos_network_storage_scripts[0].startup_script : ""
  }
}

# SLURM FILES
locals {
  ghpc_startup_dbd = {
    filename = "ghpc_startup.sh"
    content  = var.dbd_startup_script
  }
  ghpc_startup_script_dbd = length(local.daos_ns) > 0 ? [local.daos_install_mount_script, local.ghpc_startup_dbd] : [local.ghpc_startup_dbd]




  dbd_host = "${local.slurm_cluster_name}-dbd"
}

module "daos_network_storage_scripts" {
  count = length(local.daos_ns) > 0 ? 1 : 0

  source          = "github.com/GoogleCloudPlatform/hpc-toolkit//modules/scripts/startup-script?ref=v1.36.0&depth=1"
  labels          = local.labels
  project_id      = var.project_id
  deployment_name = var.deployment_name
  region          = var.region
  runners         = local.daos_network_storage_runners
}

module "slurm_files" {
  source = "../schedmd-slurm-gcp-v6-controller/modules/slurm_files"

  project_id         = var.project_id           #OK
  slurm_cluster_name = local.slurm_cluster_name #OK
  bucket_dir         = var.bucket_dir           #OK
  bucket_name        = local.bucket_name        #OK

  munge_secret = local.munge_secret #OK
  jwt_secret   = local.jwt_secret   #OK

  slurmdbd_conf_tpl = var.slurmdbd_conf_tpl #OK
  cloudsql_secret = try(
    one(google_secret_manager_secret_version.cloudsql_version[*].id),
  null) #OK

  dbd_startup_scripts         = local.ghpc_startup_script_dbd   #OK
  dbd_startup_scripts_timeout = var.dbd_startup_scripts_timeout #OK

  enable_debug_logging = var.enable_debug_logging #OK
  extra_logging_flags  = var.extra_logging_flags  #OK

  enable_bigquery_load     = var.enable_bigquery_load     #OK
  enable_slurm_gcp_plugins = var.enable_slurm_gcp_plugins #OK

  disable_default_mounts = true #OK
  network_storage = [
    for storage in var.network_storage : {
      server_ip     = storage.server_ip,
      remote_mount  = storage.remote_mount,
      local_mount   = storage.local_mount,
      fs_type       = storage.fs_type,
      mount_options = storage.mount_options
    }
    if storage.fs_type != "daos"
  ] #OK

  job_submit_lua_tpl = null
  slurm_conf_tpl     = null
  cgroup_conf_tpl    = null
  cloud_parameters   = null

  slurm_dbd_host = local.dbd_host


  depends_on = [module.bucket]

  # Providers
  endpoint_versions = var.endpoint_versions #OK
}
