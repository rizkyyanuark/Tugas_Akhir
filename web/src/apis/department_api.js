/**
 * Department management API
 */

import {
  apiAdminGet,
  apiSuperAdminGet,
  apiSuperAdminPost,
  apiSuperAdminPut,
  apiSuperAdminDelete
} from './base'

const BASE_URL = '/api/departments'

/**
 * Get the department list (accessible to regular administrators)
 * @returns {Promise<Array>} Department list
 */
export const getDepartments = () => {
  return apiAdminGet(BASE_URL)
}

/**
 * Get department details
 * @param {number} departmentId - Department ID
 * @returns {Promise<Object>} Department details
 */
export const getDepartment = (departmentId) => {
  return apiSuperAdminGet(`${BASE_URL}/${departmentId}`)
}

/**
 * Create a department
 * @param {Object} data - Department data
 * @param {string} data.name - Department name
 * @param {string} [data.description] - Department description
 * @returns {Promise<Object>} Created department
 */
export const createDepartment = (data) => {
  return apiSuperAdminPost(BASE_URL, data)
}

/**
 * Update a department
 * @param {number} departmentId - Department ID
 * @param {Object} data - Department data
 * @param {string} [data.name] - Department name
 * @param {string} [data.description] - Department description
 * @returns {Promise<Object>} Updated department
 */
export const updateDepartment = (departmentId, data) => {
  return apiSuperAdminPut(`${BASE_URL}/${departmentId}`, data)
}

/**
 * Delete a department
 * @param {number} departmentId - Department ID
 * @returns {Promise<Object>} Deletion result
 */
export const deleteDepartment = (departmentId) => {
  return apiSuperAdminDelete(`${BASE_URL}/${departmentId}`)
}

export const departmentApi = {
  getDepartments,
  getDepartment,
  createDepartment,
  updateDepartment,
  deleteDepartment
}
