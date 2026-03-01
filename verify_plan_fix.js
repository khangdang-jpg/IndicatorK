#!/usr/bin/env node
/**
 * Verification script for /plan command fix
 * Tests that the weekly plan can be loaded correctly
 */

const GITHUB_REPO = "khangdang-jpg/IndicatorK";

async function verifyWeeklyPlanAccess() {
  console.log('=== Verifying Weekly Plan Fix ===\n');

  // Test 1: Verify the JSON file is accessible
  console.log('Test 1: Checking if weekly_plan.json is accessible...');
  const url = `https://raw.githubusercontent.com/${GITHUB_REPO}/main/data/weekly_plan.json`;
  console.log(`URL: ${url}`);

  try {
    const response = await fetch(url);
    console.log(`Status: ${response.status} ${response.ok ? '✓' : '✗'}`);

    if (!response.ok) {
      console.error('✗ FAIL: Cannot access weekly_plan.json');
      return false;
    }

    const data = await response.json();
    console.log('✓ SUCCESS: JSON parsed successfully');
    console.log(`  - Generated: ${data.generated_at}`);
    console.log(`  - Week of: ${data.week_of}`);
    console.log(`  - Recommendations: ${data.recommendations.length}`);
    console.log('');

    // Test 2: Verify JSON structure
    console.log('Test 2: Validating JSON structure...');
    const requiredFields = ['generated_at', 'week_of', 'recommendations', 'market_outlook'];
    const missingFields = requiredFields.filter(field => !(field in data));

    if (missingFields.length > 0) {
      console.error(`✗ FAIL: Missing required fields: ${missingFields.join(', ')}`);
      return false;
    }
    console.log('✓ SUCCESS: All required fields present');
    console.log('');

    // Test 3: Verify recommendations structure
    console.log('Test 3: Validating recommendations...');
    if (!Array.isArray(data.recommendations) || data.recommendations.length === 0) {
      console.error('✗ FAIL: No recommendations found');
      return false;
    }

    console.log(`Found ${data.recommendations.length} recommendations:`);
    data.recommendations.forEach((rec, i) => {
      console.log(`  ${i + 1}. ${rec.action} ${rec.symbol}`);
      if (rec.rationale) {
        console.log(`     Rationale: ${rec.rationale}`);
      }
    });
    console.log('✓ SUCCESS: Recommendations are valid');
    console.log('');

    // Test 4: Check Workers endpoint
    console.log('Test 4: Checking Workers endpoint...');
    const workerUrl = 'https://indicatork-bot.khang-dang.workers.dev';
    const workerResponse = await fetch(workerUrl);
    console.log(`Workers URL: ${workerUrl}`);
    console.log(`Status: ${workerResponse.status} ${workerResponse.ok ? '✓' : '✗'}`);

    if (workerResponse.ok) {
      const text = await workerResponse.text();
      console.log(`Response: ${text}`);
      console.log('✓ SUCCESS: Workers endpoint is responding');
    } else {
      console.error('✗ FAIL: Workers endpoint not responding');
      return false;
    }

    console.log('');
    console.log('=== All Tests Passed ✓ ===');
    console.log('');
    console.log('The /plan command should now work correctly.');
    console.log('Test it by sending "/plan" to your Telegram bot.');

    return true;
  } catch (error) {
    console.error('✗ ERROR:', error.message);
    console.error('Stack trace:', error.stack);
    return false;
  }
}

// Run verification
verifyWeeklyPlanAccess().then(success => {
  process.exit(success ? 0 : 1);
});
