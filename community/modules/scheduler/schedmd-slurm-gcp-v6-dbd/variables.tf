/**
 * Copyright (C) SchedMD LLC.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

###########
# GENERAL #
###########

variable "project_id" {
  type        = string
  description = "Project ID to create resources in."
}

variable "deployment_name" {
  description = "Name of the deployment."
  type        = string
}

variable "slurm_cluster_name" {
  type        = string
  description = <<-EOD
    Cluster name, used for resource naming and slurm accounting.
    If not provided it will default to the first 8 characters of the deployment name (removing any invalid characters).
  EOD
  default     = null

  validation {
    condition     = var.slurm_cluster_name == null || can(regex("^[a-z](?:[a-z0-9]{0,9})$", var.slurm_cluster_name))
    error_message = "Variable 'slurm_cluster_name' must be a match of regex '^[a-z](?:[a-z0-9]{0,9})$'."
  }
}

variable "region" {
  type        = string
  description = "The default region to place resources in."
}

variable "zone" {
  type        = string
  description = <<EOD
Zone where the instances should be created. If not specified, instances will be
spread across available zones in the region.
EOD
  default     = null
}

##########
# BUCKET #
##########

variable "create_bucket" {
  description = <<-EOD
    Create GCS bucket instead of using an existing one.
  EOD
  type        = bool
  default     = true
}

variable "bucket_name" {
  description = <<-EOD
    Name of GCS bucket.
    Ignored when 'create_bucket' is true.
  EOD
  type        = string
  default     = null
}

variable "bucket_dir" {
  description = "Bucket directory for cluster files to be put into. If not specified, then one will be chosen based on slurm_cluster_name."
  type        = string
  default     = null
}

#########
# SLURM #
#########

variable "enable_debug_logging" {
  type        = bool
  description = "Enables debug logging mode."
  default     = false
}

variable "extra_logging_flags" {
  type        = map(bool)
  description = "The only available flag is `trace_api`"
  default     = {}
}

variable "enable_bigquery_load" {
  description = <<EOD
Enables loading of cluster job usage into big query.

NOTE: Requires Google Bigquery API.
EOD
  type        = bool
  default     = false
}

variable "network_storage" {
  description = "An array of network attached storage mounts to be configured on all instances."
  type = list(object({
    server_ip             = string,
    remote_mount          = string,
    local_mount           = string,
    fs_type               = string,
    mount_options         = string,
    client_install_runner = optional(map(string))
    mount_runner          = optional(map(string))
  }))
  default = []
}

variable "slurmdbd_conf_tpl" {
  description = "Slurm slurmdbd.conf template file path."
  type        = string
  default     = null
}

variable "dbd_startup_script" {
  description = "Startup script used by the dbd VM."
  type        = string
  default     = "# no-op"
}

variable "dbd_startup_scripts_timeout" {
  description = <<EOD
The timeout (seconds) applied to each script in dbd_startup_scripts. If
any script exceeds this timeout, then the instance setup process is considered
failed and handled accordingly.

NOTE: When set to 0, the timeout is considered infinite and thus disabled.
EOD
  type        = number
  default     = 300
}

variable "cloudsql" {
  description = <<EOD
Use this database instead of the one on the controller.
  server_ip : Address of the database server.
  user      : The user to access the database as.
  password  : The password, given the user, to access the given database. (sensitive)
  db_name   : The database to access.
EOD
  type = object({
    server_ip = string
    user      = string
    password  = string # sensitive
    db_name   = string
  })
  default   = null
  sensitive = true
}

variable "munge_secret" {
  description = <<EOD
In case munge_secret is already stored as google_secret_manager_secret
specify it using this variable. Leave it unspecified or null to generate a new
munge secret
EOD
  type        = string
  default     = null
}

variable "jwt_secret" {
  description = <<EOD
In case jwt_secret is already stored as google_secret_manager_secret
specify it using this variable. Leave it unspecified or null to generate a new
jwt secret
EOD
  type        = string
  default     = null
}

variable "enable_slurm_gcp_plugins" {
  description = <<EOD
Enables calling hooks in scripts/slurm_gcp_plugins during cluster resume and suspend.
EOD
  type        = any
  default     = false
}

variable "universe_domain" {
  description = "Domain address for alternate API universe"
  type        = string
  default     = "googleapis.com"
  nullable    = false
}

variable "endpoint_versions" {
  description = "Version of the API to use (The compute service is the only API currently supported)"
  type = object({
    compute = string
  })
  default = {
    compute = "beta"
  }
  nullable = false
}
