# Copyright 2024 "Google LLC"
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

output "slurm_dbd_instance" {
  description = "Compute instance of dbd node, if an external one is used, this is the same as var.dbd_info.dbd_addr, and if the controller instance is used for the dbd, this is null"
  value       = module.slurm_dbd_instance.slurm_instances[0].name
}

output "slurm_bucket_path" {
  description = "Bucket path used by cluster."
  value       = module.slurm_files.slurm_bucket_path
}

output "instructions" {
  description = "Post deployment instructions."
  value       = <<-EOT
    To SSH to the controller (may need to add '--tunnel-through-iap'):
      gcloud compute ssh ${module.slurm_dbd_instance.instances_self_links[0]}
  EOT
}

output "munge_secret" {
  description = "The google_secret_manager secret where the munge secret is."
  value       = local.munge_secret
}

output "jwt_secret" {
  description = "The google_secret_manager secret where the jwt secret is."
  value       = local.jwt_secret
}
